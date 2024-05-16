import logging
import threading
from collections import deque
from queue import Queue
from struct import pack

import serial
import termios

import pymultidropbus.helpers

CMSPAR = 0x40000000

SEND_POLL_COMMANDS = False  # be careful, there's A LOT of these and the library already handles the ACKs
SEND_CC_COMMANDS = False
SEND_BV_COMMANDS = False

logger = logging.getLogger("pymultidropbus")


class IncomingCommandThread(threading.Thread):
    def __init__(self, mdb_client: "pymultidropbus.MDB", log_level=logging.INFO):
        super().__init__()
        self._stop_event = threading.Event()
        self.mdb = mdb_client

        logging.basicConfig(level=log_level)
        self.logger = logging.getLogger("pymultidropbus:incoming_command_thread")

    def stop(self):
        self._stop_event.set()

    def stopped(self):
        return self._stop_event.is_set()

    def run(self):
        while self._stop_event.is_set() is False:
            self.mdb.check_for_command()


class MDB:
    def __init__(self, commands_queue: "Queue[str]", com_port: str = "/dev/ttyAMA0", baudrate: str = 9600,
                 log_level=logging.INFO):
        logger.setLevel(log_level)
        self.commands_queue = commands_queue
        self.serial_port = serial.Serial(
            com_port, baudrate, 8, serial.PARITY_SPACE, timeout=0.01
        )
        logger.info("Connected to: " + self.serial_port.name)
        self.serial_port.reset_input_buffer()
        self._mode_bit_enable_mark()

        self.reader_state = "inactive"
        self.session_balance = None
        self.cashless_mdb_queue = Queue()

        self.incoming_command_thread = IncomingCommandThread(self)
        self.incoming_command_thread.start()

    def _mode_bit_enable_mark(self):
        iflag, oflag, cflag, lflag, ispeed, ospeed, cc = termios.tcgetattr(self.serial_port)
        iflag |= termios.PARMRK | termios.INPCK
        iflag &= ~termios.IGNPAR
        termios.tcsetattr(self.serial_port, termios.TCSANOW, [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])

    def _mode_bit_off(self):
        iflag, oflag, cflag, lflag, ispeed, ospeed, cc = termios.tcgetattr(self.serial_port)
        cflag |= termios.PARENB | CMSPAR
        cflag &= ~termios.PARODD
        termios.tcsetattr(self.serial_port, termios.TCSANOW, [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])

    def _mode_bit_on(self):
        iflag, oflag, cflag, lflag, ispeed, ospeed, cc = termios.tcgetattr(self.serial_port)
        cflag |= termios.PARENB | CMSPAR | termios.PARODD
        termios.tcsetattr(self.serial_port, termios.TCSANOW, [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])

    def send_ack(self):
        self._mode_bit_on()
        self.serial_port.write(bytearray.fromhex("00"))
        self._mode_bit_off()

    def _send_just_reset(self):
        self._send_cmd("00")

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

        logger.debug("Wrote cmd: " + command_string + " {:02X}".format(check_byte))

    def _queue_poll_response(self, command_string: str, reader_state: str = None):
        queued_response = {
            "mdb_command": command_string
        }
        if reader_state:
            queued_response["reader_state"] = reader_state
        self.cashless_mdb_queue.put(queued_response)

    def deny_vend(self):
        self._queue_poll_response("06", "idle")

    def approve_vend(self, amount_charged_in_cents: int):
        amount_charged_in_hex = helpers.cents_to_hex(amount_charged_in_cents * 10)  # must be scaled by 10x for the VMC
        self._queue_poll_response("05" + amount_charged_in_hex, "idle")

    def start_cashless_session(self, available_balance_in_cents: int = None):
        if self.reader_state == "enabled":
            logger.info("Queueing start cashless session")
            available_balance_in_hex = "FFFF"  # defaults to unknown
            if available_balance_in_cents:
                available_balance_in_hex = helpers.int_to_hex(available_balance_in_cents)
                self.session_balance = None

            command = "03" + available_balance_in_hex.zfill(4)
            self._queue_poll_response(command, "idle")
        else:
            logger.warning("Reader not enabled, cannot start cashless session")

    def reader_cancelled(self):
        self._queue_poll_response("08")

    def session_completed(self):
        self._queue_poll_response("07")

    def process_cmd(self, cmd: str):
        if cmd == "00":
            logger.debug("Got ACK")

        elif cmd == "AA":
            logger.info("Got RET :(")

        elif cmd == "FF":
            logger.info("Got NACK")

        elif cmd == "08":
            # maybe one day this library will support being a coin changer
            # logger.debug("Got CC RESET")
            # self.commands_queue.put(helpers.get_command_object("CC_RESET"))
            pass

        elif cmd == "0B":
            # maybe one day this library will support being a coin changer
            # logger.debug("Got CC POLL")
            # if SEND_POLL_COMMANDS:
            #     self.commands_queue.put(helpers.get_command_object("CC_POLL"))
            pass

        elif cmd == "30":
            # maybe one day this library will support being a bill validator
            # logger.debug("Got BV RESET")
            # self.send_ack()
            # if SEND_BV_COMMANDS:
            #     self.commands_queue.put(helpers.get_command_object("BV_RESET"))
            pass

        elif cmd == "33":
            # maybe one day this library will support being a coin changer
            # logger.debug("Got BV POLL")
            # if SEND_POLL_COMMANDS:
            #     self.commands_queue.put(helpers.get_command_object("BV_POLL"))
            pass

        elif cmd == "10":
            self.send_ack()
            logger.info("Got CSH RESET")
            self.reader_state = "inactive"
            self.commands_queue.put(helpers.get_command_object("CSH_RESET"))

        elif cmd[:4] == "1100":
            logger.info("Got CSH SETUP Config Data")
            vmc_feature_level = helpers.hex_to_int(cmd[4:6])
            columns_on_display = helpers.hex_to_int(cmd[6:8])
            rows_on_display = helpers.hex_to_int(cmd[8:10])
            display_type = helpers.hex_to_int(cmd[10:12])
            logger.info(f"VMC feature level: {vmc_feature_level} Columns on display: {columns_on_display} "
                        f"Rows on display: {rows_on_display} Display type: {display_type}")

            data = {
                "vmc_feature_level": vmc_feature_level,
                "columns_on_display": columns_on_display,
                "rows_on_display": rows_on_display,
                "display_type": display_type
            }
            self.commands_queue.put(helpers.get_command_object("CSH_RESET", data))

        elif cmd[:4] == "1101":
            self.send_ack()
            max_price = helpers.hex_to_int(cmd[4:8]) / 10
            min_price = helpers.hex_to_int(cmd[8:12]) / 10
            logger.info(f"Got CSH SETUP Min/Max Prices. Min: ${min_price} Max: ${max_price}")

            self.reader_state = "disabled"

            data = {
                "max_price": max_price,
                "min_price": min_price
            }
            self.commands_queue.put(helpers.get_command_object("CSH_SETUP", data))

        elif cmd == "12":
            # logger.debug("Got CSH POLL 12")
            if self.reader_state == "inactive":
                self._send_just_reset()
                self.reader_state = "disabled"
            elif self.reader_state == "disabled":
                self.send_ack()
            elif not self.cashless_mdb_queue.empty():
                queued_command = self.cashless_mdb_queue.get()
                mdb_command = queued_command.get("mdb_command")
                if queued_command.get("reader_state"):
                    self.reader_state = queued_command.get("reader_state")
                self._send_cmd(mdb_command)
                self.cashless_mdb_queue.task_done()
            else:
                self.send_ack()

            if SEND_POLL_COMMANDS:
                self.commands_queue.put(helpers.get_command_object("CSH_POLL"))

        elif cmd[:4] == "1300":
            self.send_ack()
            item_price = helpers.hex_to_int(cmd[4:8]) * 10
            item_number = None if helpers.hex_to_int(cmd[8:12]) == 0xFFFF else helpers.hex_to_int(cmd[8:12])
            logger.info(f"Got VEND REQUEST. Item price: {item_price} cents Item number: {item_number}")
            self.reader_state = "vend"

            data = {
                "item_price": item_price,
                "item_number": item_number,
            }
            self.commands_queue.put(helpers.get_command_object("VEND_REQUEST", data))

        elif cmd[:4] == "1301":
            logger.info("Got VEND CANCEL REQUEST")
            self.deny_vend()
            self.reader_state = "idle"
            self.commands_queue.put(helpers.get_command_object("VEND_CANCELLED"))

        elif cmd[:4] == "1302":
            self.send_ack()
            item_number = None if helpers.hex_to_int(cmd[4:8]) == 0xFFFF else helpers.hex_to_int(cmd[4:8])
            logger.info(f"Got VEND SUCCESS. Item number: {item_number}")
            self.reader_state = "idle"

            self.commands_queue.put(helpers.get_command_object("VEND_SUCCESS", {"item_number": item_number}))

        elif cmd[:4] == "1303":
            self.send_ack()
            logger.info("Got VEND FAILURE.")
            self.reader_state = "enabled"
            self.commands_queue.put(helpers.get_command_object("VEND_FAILURE"))

        elif cmd[:4] == "1304":
            self.send_ack()
            logger.info("Got VEND SESSION COMPLETE.")
            self.commands_queue.put(helpers.get_command_object("VEND_SESSION_COMPLETE"))
            self.reader_state = "enabled"
            self.session_completed()

        elif cmd[:4] == "1400":
            self.send_ack()
            logger.info("Got CSH READER DISABLE.")
            self.reader_state = "disabled"
            self.commands_queue.put(helpers.get_command_object("CSH_READER_DISABLED"))

        elif cmd[:4] == "1401":
            self.send_ack()
            logger.info("Got CSH READER ENABLE")
            self.reader_state = "enabled"
            self.commands_queue.put(helpers.get_command_object("CSH_READER_ENABLED"))

        elif cmd[:4] == "1402":
            self.reader_cancelled()
            logger.info("Got CSH READER CANCEL")
            self.reader_state = "enabled"
            self.commands_queue.put(helpers.get_command_object("CSH_READER_CANCEL"))

        elif cmd[:4] == "1700":
            manufacturer_code = helpers.get_ascii_from_hex(cmd[4:10])
            serial_number = helpers.get_ascii_from_hex(cmd[10:34])
            model_number = helpers.get_ascii_from_hex(cmd[34:58])
            software_version = helpers.hex_to_int(cmd[58:62])
            logger.info(
                f"Got CSH EXPANSION. Mfr: {manufacturer_code} Serial: {serial_number} Model: {model_number} Software Version: {software_version}")

            data = {
                "manufacturer_code": manufacturer_code,
                "serial_number": serial_number,
                "model_number": model_number,
                "software_version": software_version
            }
            self.commands_queue.put(helpers.get_command_object("CSH_EXPANSION", data))

        else:
            logger.warning("Received unknown mdb command: " + cmd)
            self.commands_queue.put(helpers.get_command_object("UNKNOWN_CMD", {"command": cmd}))

    def check_for_command(self):
        start_bytes = deque(["xx"] * 2, maxlen=2)

        # Keep reading through bytes until we get the start of a packet. The start of a packet is always an address byte
        # with the 9th bit set, which shows as a parity error, which Linux marks by prepending 0xFF 0x00 to the byte.
        while "".join(start_bytes) != "FF00":
            new_byte = self.serial_port.read(size=1).hex().upper()
            if new_byte:
                start_bytes.append(new_byte)

        command = self.serial_port.read(size=1).hex().upper()

        # return straight away, these special packets don't have a checksum
        if command in ["00", "AA", "FF"]:
            self.process_cmd(command)
            return

        while True:
            # MDB packets can't be longer than 36 bytes. If we get to this point and the command is longer than 36
            # bytes, something has gone wrong and we've probably got multiple packets all smashed together. Because we
            # are relying on Linux to prepend 0xFF 0x00 to mark the 9th bit being set in address bytes, and these bytes
            # may appear in the packet itself, we can't reliably use this to detect the start of a new packet halfway
            # through a stream of bytes.

            if len(command) > 36 * 2:  # * 2 because we're working with hex strings (e.g. FF)
                logger.warning("Command too long, discarding: " + command)
                return

            # keep reading individual bytes until we get the checksum
            new_byte = self.serial_port.read(size=1).hex().upper()
            if new_byte:
                full_command_checksum = helpers.get_chk(command)  # get checksum of all existing bytes

                # if the new byte is the checksum, we've got all the bytes so process the command
                if helpers.hex_to_int(new_byte) == full_command_checksum:
                    self.process_cmd(command)
                    return
                else:
                    # if it's not the checksum yet, add the byte and keep going
                    command += new_byte

            else:
                # we timed out while waiting for the next byte
                logger.debug("Corrupt command, discarding: " + command)
                return
