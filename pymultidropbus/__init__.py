import threading
from queue import Queue
from struct import pack

import serial
import termios

import pymultidropbus.helpers

CMSPAR = 0x40000000

QUEUE_POLL_COMMANDS = False
QUEUE_CC_COMMANDS = False
QUEUE_BV_COMMANDS = False


class MDB:
    def __init__(self, commands_queue: "Queue[str]", com_port: str = "/dev/ttyAMA0", baudrate: str = 9600):
        self.commands_queue = commands_queue
        self.serial_port = serial.Serial(
            com_port, baudrate, 8, serial.PARITY_SPACE, timeout=0.01
        )
        print("Connected to: ")
        print(self.serial_port.name)
        self.serial_port.reset_input_buffer()
        self._mode_bit_enable_mark()

        self.reader_state = "inactive"
        self.session_state = "idle"

        self.event = threading.Event()
        self.incoming_command_thread = threading.Thread(daemon=True, target=self.check_for_command, name="incoming_command_thread")
        self.incoming_command_thread.start()

    def _mode_bit_enable_mark(self):
        iflag,oflag,cflag,lflag,ispeed,ospeed,cc = termios.tcgetattr(self.serial_port)
        iflag |= termios.PARMRK | termios.INPCK
        iflag &= ~termios.IGNPAR
        termios.tcsetattr(self.serial_port, termios.TCSANOW, [iflag,oflag,cflag,lflag,ispeed,ospeed,cc])

    def _mode_bit_off(self):
        iflag,oflag,cflag,lflag,ispeed,ospeed,cc = termios.tcgetattr(self.serial_port)
        cflag |= termios.PARENB | CMSPAR
        cflag &= ~termios.PARODD
        termios.tcsetattr(self.serial_port, termios.TCSANOW, [iflag,oflag,cflag,lflag,ispeed,ospeed,cc])

    def _mode_bit_on(self):
        iflag,oflag,cflag,lflag,ispeed,ospeed,cc = termios.tcgetattr(self.serial_port)
        cflag |= termios.PARENB | CMSPAR | termios.PARODD
        termios.tcsetattr(self.serial_port, termios.TCSANOW, [iflag,oflag,cflag,lflag,ispeed,ospeed,cc])

    def _send_ack(self):
        self._mode_bit_on()
        self.serial_port.write(bytearray.fromhex("00"))
        self._mode_bit_off()

    def _send_cmd(self, command_string):
        command_string = command_string.replace(" ", "")
        check_byte = helpers.get_chk(command_string)
        command = bytearray.fromhex(command_string)
        command_chk_byte = pack("B", check_byte)

        # let's write all our data bytes and wait for them to send
        for byte in command:
            self.serial_port.write(pack("B", byte))
        helpers.wait_for_output_buffer_to_clear(command)

        # now toggle the mode bit and write the chk byte
        self._mode_bit_on()
        self.serial_port.write(command_chk_byte)
        helpers.wait_for_output_buffer_to_clear(command_chk_byte)
        self._mode_bit_off()

        #print("wrote cmd: " + command_string + " {:02X}".format(check_byte))

    def deny_vend(self):
        self._send_cmd("06")
        self.reader_state = "idle"

    def approve_vend(self, amount_charged_in_cents: int):
        amount_charged_in_hex = helpers.cents_to_hex(amount_charged_in_cents * 10)  # must be scaled by 10x for the VMC
        self._send_cmd("05" + amount_charged_in_hex)
        self.reader_state = "idle"

    def start_cashless_session(self, available_balance_in_cents: int = 0):
        available_balance_in_hex = "FFFF"  # defaults to unknown
        if available_balance_in_cents:
            available_balance_in_cents = int(available_balance_in_cents * 10)  # must be scaled by 10x for the VMC
            available_balance_in_hex = helpers.int_to_hex(available_balance_in_cents)

        self._send_cmd("03" + available_balance_in_hex)
        self.reader_state = "idle"

    def reader_cancelled(self):
        self._send_cmd("08")

    def reader_session_ended(self):
        self._send_cmd("07")

    def parse_cmd(self):
        command = self.serial_port.read(size=1).hex().upper()

        if command in ["00", "AA", "FF"]:
            # return straight away, these special commands don't have a checksum
            return command

        full_command = command
        while True:
            if len(full_command) > 36*2:
                print("WARN: command too long, discarding: " + full_command)
                self.serial_port.reset_input_buffer()
                return ""
            new_byte = self.serial_port.read(size=1).hex().upper()
            full_command_checksum = helpers.get_chk(full_command)
            new_byte_checksum = helpers.get_chk(new_byte)

            if new_byte_checksum == full_command_checksum:
                # we're at the end of the data block so return it
                return full_command
            else:
                full_command += new_byte

    def check_for_command(self):
        while not self.event.is_set():
            cmd_raw = self.serial_port.read(size=2).hex().upper()

            # this is the start of a new address byte
            if cmd_raw == "FF00":
                cmd = self.parse_cmd()

                if cmd == "00":
                    print("Got ACK")

                elif cmd == "AA":
                    print("Got RET :(")

                elif cmd == "FF":
                    print("Got NACK")

                elif cmd == "08":
                    # print("Got CC RESET")
                    if QUEUE_CC_COMMANDS:
                        self.commands_queue.put(helpers.get_command_object("CC_RESET"))

                elif cmd == "0B":
                    # print("Got CC POLL")
                    if QUEUE_POLL_COMMANDS and QUEUE_CC_COMMANDS:
                        self.commands_queue.put(helpers.get_command_object("CC_POLL"))

                elif cmd == "30":
                    # print("Got BV RESET")
                    self._send_ack()
                    if QUEUE_BV_COMMANDS:
                        self.commands_queue.put(helpers.get_command_object("BV_RESET"))

                elif cmd == "33":
                    # print("Got BV POLL")
                    if QUEUE_POLL_COMMANDS and QUEUE_BV_COMMANDS:
                        self.commands_queue.put(helpers.get_command_object("BV_POLL"))

                elif cmd == "10":
                    print("Got CSH RESET")
                    self.reader_state = "inactive"
                    self._send_ack()
                    self.commands_queue.put(helpers.get_command_object("CSH_RESET"))

                elif cmd[:4] == "1100":
                    print("Got CSH SETUP Config Data")
                    vmc_feature_level = helpers.hex_to_int(cmd[4:6])
                    columns_on_display = helpers.hex_to_int(cmd[6:8])
                    rows_on_display = helpers.hex_to_int(cmd[8:10])
                    display_type = helpers.hex_to_int(cmd[10:12])
                    print(f"VMC feature level: {vmc_feature_level} Columns on display: {columns_on_display} "
                          f"Rows on display: {rows_on_display} Display type: {display_type}")

                    # reader config data
                    self._send_cmd("01 01 10 36 0A 02 07 0D")  # TODO: remove and let upper layer handle this
                    data = {
                        "vmc_feature_level": vmc_feature_level,
                        "columns_on_display": columns_on_display,
                        "rows_on_display": rows_on_display,
                        "display_type": display_type
                    }
                    self.commands_queue.put(helpers.get_command_object("CSH_RESET", data))

                elif cmd[:4] == "1101":
                    print("Got CSH SETUP Min/Max Prices ")
                    max_price = helpers.hex_to_int(cmd[4:8]) / 10
                    min_price = helpers.hex_to_int(cmd[8:12]) / 10
                    print(f"Min price: ${min_price} Max price: ${max_price}")

                    self.reader_state = "disabled"
                    self._send_ack()

                    data = {
                        "max_price": max_price,
                        "min_price": min_price
                    }
                    self.commands_queue.put(helpers.get_command_object("CSH_SETUP", data))

                elif cmd == "12":
                    # print("Got CSH POLL 12")
                    if self.reader_state == "inactive":
                        self._send_cmd("00")  # JUST RESET
                        self.reader_state = "disabled"
                    else:
                        self._send_ack()
                    if QUEUE_POLL_COMMANDS:
                        self.commands_queue.put(helpers.get_command_object("CSH_POLL"))

                elif cmd[:4] == "1300":
                    print("Got VEND REQUEST")
                    self._send_ack()
                    item_price = helpers.hex_to_int(cmd[4:8]) / 10
                    item_number = None if helpers.hex_to_int(cmd[8:12]) == 0xFFFF else helpers.hex_to_int(cmd[8:12])
                    print(f"Item price: ${item_price} Item number: {item_number}")
                    self.reader_state = "vend"

                    data = {
                        "item_price": item_price,
                        "item_number": item_number,
                    }
                    self.commands_queue.put(helpers.get_command_object("VEND_REQUEST", data))

                elif cmd[:4] == "1301":
                    print("Got VEND CANCEL REQUEST")
                    self.deny_vend()
                    self.reader_state = "idle"
                    self.commands_queue.put(helpers.get_command_object("VEND_CANCELLED"))

                elif cmd[:4] == "1302":
                    print("Got VEND SUCCESS")
                    item_number = None if helpers.hex_to_int(cmd[4:8]) == 0xFFFF else helpers.hex_to_int(cmd[4:8])
                    print(f"Item number: {item_number}")
                    self.reader_state = "idle"

                    self._send_ack()
                    self.commands_queue.put(helpers.get_command_object("VEND_SUCCESS", {"item_number": item_number}))

                elif cmd[:4] == "1303":
                    print("Got VEND FAILURE")
                    self.reader_state = "enabled"
                    self.commands_queue.put(helpers.get_command_object("VEND_FAILURE"))

                    # TODO: remove and let upper layer handle this - customer refund needed
                    refund_success = True
                    if refund_success:
                        self._send_ack()
                    else:
                        # TODO: send MALFUNCTION ERROR code 1100yyyy
                        self._send_cmd("")

                    self.start_cashless_session()

                elif cmd[:4] == "1304":
                    print("Got VEND SESSION COMPLETE")
                    self.reader_state = "enabled"
                    self.reader_session_ended()
                    self.commands_queue.put(helpers.get_command_object("VEND_SESSION_COMPLETE"))
                    self.start_cashless_session()

                elif cmd[:4] == "1304":
                    print("Got CASH SALE")
                    item_price = helpers.hex_to_int(cmd[4:8]) / 10
                    item_number = None if helpers.hex_to_int(cmd[8:12]) == 0xFFFF else helpers.hex_to_int(cmd[8:12])
                    print(f"Item price: ${item_price} Item number: {item_number}")

                    self._send_ack()
                    data = {
                        "item_price": item_price,
                        "item_number": item_number
                    }
                    self.commands_queue.put(helpers.get_command_object("CASH_SALE", data))

                elif cmd[:4] == "1400":
                    print("Got CSH READER DISABLE")
                    self.reader_state = "disabled"
                    self._send_ack()
                    self.commands_queue.put(helpers.get_command_object("CSH_READER_DISABLED"))

                elif cmd[:4] == "1401":
                    print("Got CSH READER ENABLE")
                    self.reader_state = "enabled"
                    self._send_ack()
                    self.commands_queue.put(helpers.get_command_object("CSH_READER_ENABLED"))

                elif cmd[:4] == "1402":
                    print("Got CSH READER CANCEL")
                    self.reader_state = "enabled"
                    self.reader_cancelled()
                    self.commands_queue.put(helpers.get_command_object("CSH_READER_CANCEL"))
                    self.start_cashless_session()

                elif cmd[:4] == "1700":
                    print("Got CSH EXPANSION ")
                    manufacturer_code = helpers.get_ascii_from_hex(cmd[4:10])
                    serial_number = helpers.get_ascii_from_hex(cmd[10:34])
                    model_number = helpers.get_ascii_from_hex(cmd[34:58])
                    software_version = helpers.hex_to_int(cmd[58:62])

                    print(f"Manufacturer code: {manufacturer_code} Serial number: {serial_number} Model number: {model_number}"
                          f" Software version: {software_version}")

                    # reader peripheral id data
                    # TODO: document and generate this dynamically
                    self._send_cmd("09 42 4D 53 30 30 30 30 30 30 30 30 30 30 30 31 30 30 30 30 30 30 30 30 30 30 30 31 01 01")
                    data = {
                        "manufacturer_code": manufacturer_code,
                        "serial_number": serial_number,
                        "model_number": model_number,
                        "software_version": software_version
                    }
                    self.commands_queue.put(helpers.get_command_object("CSH_EXPANSION", data))

                else:
                    print("WARNING: received unknown cmd: " + cmd)
                    self.commands_queue.put(helpers.get_command_object("UNKNOWN_CMD", {"command": cmd}))

            elif cmd_raw:
                print("WARNING: received non address bytes (probably corrupt data): " + cmd_raw)
