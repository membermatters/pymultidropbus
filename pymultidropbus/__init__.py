import logging
import termios
import threading
from collections import deque
from queue import Queue
from struct import pack
import os

import serial

import pymultidropbus.helpers
import pymultidropbus.protocol as protocol
import pymultidropbus.protocol.peripherals.Cashless as Cashless
from pymultidropbus.protocol import Vmc

CMSPAR = 0x40000000

SEND_POLL_COMMANDS = False  # be careful, there's A LOT of these and the library already handles the ACKs
SEND_CC_COMMANDS = False
SEND_BV_COMMANDS = False

logging.basicConfig()
logger = logging.getLogger("pymultidropbus")


class IncomingCommandThread(threading.Thread):
    def __init__(self, mdb_client: "pymultidropbus.Peripheral", log_level=logging.INFO, process_affinity=None):
        super().__init__()
        self._stop_event = threading.Event()
        self.mdb = mdb_client

        self.logger = logging.getLogger("pymultidropbus:incoming_command_thread")
        self.logger.setLevel(log_level)
        self.logger.debug("Incoming command thread started")
        self.process_affinity = process_affinity

    def start(self):
        if self.process_affinity:
            affinity_mask = {self.process_affinity}
            pid = 0  # 0 is the current process
            os.sched_setaffinity(pid, affinity_mask)
        super().start()

    def stop(self):
        self._stop_event.set()

    def stopped(self):
        return self._stop_event.is_set()

    def run(self):
        while self._stop_event.is_set() is False:
            self.mdb.check_for_command()


class Peripheral:
    def __init__(self,
                 event_queue: "Queue[protocol.MdbCommandEvent]",
                 com_port: str = "/dev/ttyAMA0",
                 baudrate: str = 9600,
                 enable_unsupported_commands: bool = False,
                 enable_default_responses: bool = True,
                 log_level=logging.DEBUG,
                 report_acks: bool = False,
                 process_affinity=None):
        logger.setLevel(log_level)
        self.mdb_send_queue = Queue()  # we use this to queue up commands that have to wait for a poll command
        self.event_queue = event_queue  # we publish events to this queue to be consumed outside this library
        self.enable_unsupported_commands = enable_unsupported_commands  # publish unsupported/unknown commands
        self.enable_default_responses = enable_default_responses  # send default responses to commands like ACKs etc.
        self.report_acks = report_acks  # report ACKs to the event queue
        self.serial_port = serial.Serial(
            com_port, baudrate, 8, serial.PARITY_SPACE, timeout=0.01
        )
        logger.info("Connected to: " + self.serial_port.name)
        self.serial_port.reset_input_buffer()
        self.mode_bit_enabled = False
        self._mode_bit_enable_mark()

        # This handles incoming commands from the MDB bus
        self.incoming_command_thread = IncomingCommandThread(self, process_affinity=process_affinity)
        self.incoming_command_thread.start()

    def _mode_bit_enable_mark(self):
        # logger.debug("Enabling mark parity")
        iflag, oflag, cflag, lflag, ispeed, ospeed, cc = termios.tcgetattr(self.serial_port)
        iflag |= termios.PARMRK | termios.INPCK
        iflag &= ~termios.IGNPAR
        termios.tcsetattr(self.serial_port, termios.TCSANOW, [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])

    def _mode_bit_off(self):
        # logger.debug("Disabling mode bit")
        iflag, oflag, cflag, lflag, ispeed, ospeed, cc = termios.tcgetattr(self.serial_port)
        cflag |= termios.PARENB | CMSPAR
        cflag &= ~termios.PARODD
        termios.tcsetattr(self.serial_port, termios.TCSANOW, [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])
        self.mode_bit_enabled = False

    def _mode_bit_on(self):
        # logger.debug("Enabling mode bit")
        iflag, oflag, cflag, lflag, ispeed, ospeed, cc = termios.tcgetattr(self.serial_port)
        cflag |= termios.PARENB | CMSPAR | termios.PARODD
        termios.tcsetattr(self.serial_port, termios.TCSANOW, [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])
        self.mode_bit_enabled = True

    def send_ack(self):
        self._mode_bit_on()
        if self.report_acks:
            logger.debug("Sending ACK")
        self.serial_port.write(bytearray.fromhex("00"))
        self._mode_bit_off()

    def _send_just_reset(self):
        logger.debug("Sending just reset")
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
        logger.debug("Wrote cmd: " + command_string + " {:02X}".format(check_byte))
        self._mode_bit_off()

    def _queue_poll_response(self, command_string: str):
        queued_response = {
            "mdb_command": command_string
        }
        self.mdb_send_queue.put(queued_response)

    def process_cmd(self, command):
        raise NotImplementedError("You must implement this method in a subclass")

    def check_for_command(self):
        start_bytes = deque(["xx"] * 2, maxlen=2)

        # Keep reading through bytes until we get the start of a packet. The start of a packet is always an address byte
        # with the 9th bit set, which shows as a parity error, which Linux marks by prepending 0xFF 0x00 to the byte.
        while "".join(start_bytes) != "FF00":
            try:
                new_byte = self.serial_port.read(size=1).hex().upper()
                if new_byte:
                    start_bytes.append(new_byte)
            except Exception:
                continue

        command = self.serial_port.read(size=1).hex().upper()

        # return straight away, these special packets don't have a checksum
        if command in ["00", "AA", "FF"]:
            self.process_cmd(command)
            return

        while True:
            # MDB packets can't be longer than 36 bytes. If we get to this point and the command is longer than 36
            # bytes, something has gone wrong, and we've probably got multiple packets all smashed together. Because we
            # are relying on Linux to prepend 0xFF 0x00 to mark the 9th bit being set in address bytes, and these bytes
            # may appear in the packet itself, we can't reliably use this to detect the start of a new packet halfway
            # through a stream of bytes.

            if len(command) > 36 * 2:  # * 2 because we're working with hex strings (e.g. FF)
                logger.warning("Command too long, discarding: " + command)
                return

            # keep reading individual bytes until we get the checksum
            new_byte = self.serial_port.read(size=1).hex().upper()
            full_command_checksum = helpers.get_chk(command)  # get checksum of all existing bytes

            if new_byte:
                # if the new byte is the checksum, we've got all the bytes so process the command
                if helpers.hex_to_int(new_byte) == full_command_checksum:
                    self.process_cmd(command)
                    return
                else:
                    # if it's not the checksum yet, add the byte and keep going
                    command += new_byte

            else:
                # we timed out while waiting for the next byte
                if command:
                    logger.debug(f"Command: {command} New Byte: {new_byte} Checksum: {full_command_checksum}")
                    logger.debug("Corrupt command, discarding: " + command)
                return


class CashlessPeripheral(Peripheral):
    def __init__(self,
                 event_queue: "Queue[protocol.MdbCommandEvent]",
                 com_port: str = "/dev/ttyAMA0",
                 baudrate: str = 9600,
                 enable_unsupported_commands: bool = False,
                 enable_default_responses: bool = True,
                 log_level=logging.DEBUG,
                 report_acks: bool = False,
                 process_affinity=None):
        super().__init__(event_queue, com_port, baudrate, enable_unsupported_commands, enable_default_responses,
                         log_level, report_acks, process_affinity)
        self.reader_state: Cashless.State = Cashless.State.INACTIVE
        self.session_balance: protocol.Money or None = None

    def deny_vend(self) -> None:
        self._queue_poll_response(Cashless.MdbResponse.DENY_VEND.build())
        self.reader_state = Cashless.State.IDLE

    def approve_vend(self, amount_charged_in_cents: int) -> None:
        money = protocol.Money(amount_charged_in_cents)
        command = Cashless.MdbResponse.APPROVE_VEND.build(money)
        logger.info("Approving vend and sending: " + command)
        self._queue_poll_response(command)

    def start_cashless_session(self, available_balance_in_cents: int = None) -> bool:
        if self.reader_state == Cashless.State.ENABLED:
            logger.info("Queueing start cashless session")
            self.session_balance = protocol.UNKNOWN_MONEY_VALUE  # defaults to unknown
            if available_balance_in_cents:
                self.session_balance = protocol.Money(available_balance_in_cents)

            command = Cashless.MdbResponse.BEGIN_SESSION.build(self.session_balance)
            self._queue_poll_response(command)
            return True
        else:
            logger.warning("Reader not enabled, cannot start cashless session")
            return False

    def end_session(self):
        self._queue_poll_response(Cashless.MdbResponse.END_SESSION.build())

    def cancelled(self):
        self._queue_poll_response(Cashless.MdbResponse.CANCELLED.build())

    def process_cmd(self, raw_cmd: str):
        try:
            addressed_cmd = Cashless.AddressedMdbCommand(raw_cmd)
            cmd = addressed_cmd.MdbCommand
            device_address = addressed_cmd.DeviceAddress

            if cmd == protocol.MdbCommand.ACK:
                if self.report_acks:
                    logger.debug("Got ACK")
                    self.event_queue.put(protocol.AckCommandEvent())

            elif cmd == protocol.MdbCommand.RET:
                logger.warning("Got RET :(")
                self.event_queue.put(protocol.RetCommandEvent())

            elif cmd == protocol.MdbCommand.NAK:
                logger.warning("Got NAK")
                self.event_queue.put(protocol.NakCommandEvent())

            elif cmd == Cashless.MdbCommand.RESET:
                self.send_ack()
                logger.debug("Got CSH RESET")
                self.reader_state = Cashless.State.INACTIVE
                self.event_queue.put(protocol.MdbCommandEvent(Cashless.MdbCommand.RESET))

            elif cmd == Cashless.MdbCommand.SETUP_CONFIG_DATA:
                logger.debug("Got CSH SETUP Config Data")
                raw_feature_level = helpers.hex_to_int(raw_cmd[4:6])
                columns_on_display = helpers.hex_to_int(raw_cmd[6:8])
                rows_on_display = helpers.hex_to_int(raw_cmd[8:10])
                raw_display_type = helpers.hex_to_int(raw_cmd[10:12])
                logger.debug(f"VMC feature level: {raw_feature_level} Columns on display: {columns_on_display} "
                            f"Rows on display: {rows_on_display} Display type: {raw_display_type}")

                display = Cashless.VmcDisplay(rows_on_display, columns_on_display, raw_display_type)
                feature_level = Vmc.FeatureLevel(raw_feature_level)
                self.event_queue.put(Cashless.SetupConfigDataCommandEvent(feature_level, display))

            elif cmd == Cashless.MdbCommand.SETUP_PRICE_DATA:
                self.send_ack()
                max_price = protocol.Money.from_vmc_hex(raw_cmd[4:8])
                min_price = protocol.Money.from_vmc_hex(raw_cmd[8:12])
                logger.debug(f"Got CSH SETUP Min/Max Prices. Min: {min_price} Max: {max_price}")
                self.reader_state = Cashless.State.DISABLED

                self.event_queue.put(Cashless.SetupPriceCommandEvent(min_price, max_price))

            elif cmd == Cashless.MdbCommand.POLL:
                if self.reader_state == Cashless.State.INACTIVE:
                    self._send_just_reset()
                    self.reader_state = Cashless.State.DISABLED
                elif self.reader_state == Cashless.State.DISABLED:
                    self.send_ack()
                elif not self.mdb_send_queue.empty():
                    queued_command = self.mdb_send_queue.get()
                    mdb_command = queued_command.get("mdb_command")
                    self._send_cmd(mdb_command)
                    self.mdb_send_queue.task_done()
                else:
                    self.send_ack()

                if SEND_POLL_COMMANDS:
                    self.event_queue.put(protocol.MdbCommandEvent(Cashless.MdbCommand.POLL))

            elif cmd == Cashless.MdbCommand.VEND_REQUEST:
                self.send_ack()
                item_price = protocol.Money.from_vmc_hex(raw_cmd[4:8])
                item_number = None if helpers.hex_to_int(raw_cmd[8:12]) == protocol.UNKNOWN_ITEM_NUMBER else helpers.hex_to_int(raw_cmd[8:12])
                logger.debug(f"Got VEND REQUEST. Item price: {item_price} cents Item number: {item_number}")
                self.reader_state = Cashless.State.VEND

                self.event_queue.put(Cashless.VendRequestCommandEvent(item_price, item_number))

            elif cmd == Cashless.MdbCommand.VEND_CANCEL:
                logger.debug("Got VEND CANCEL REQUEST")
                self.deny_vend()
                self.reader_state = Cashless.State.ENABLED
                self.event_queue.put(protocol.MdbCommandEvent(Cashless.MdbCommand.VEND_CANCEL))

            elif cmd == Cashless.MdbCommand.VEND_SUCCESS:
                self.send_ack()
                item_number = None if helpers.hex_to_int(raw_cmd[4:8]) == protocol.UNKNOWN_ITEM_NUMBER else helpers.hex_to_int(raw_cmd[4:8])
                logger.debug(f"Got VEND SUCCESS. Item number: {item_number}")
                self.reader_state = Cashless.State.ENABLED

                self.event_queue.put(Cashless.VendSuccessCommandEvent(item_number))

            elif cmd == Cashless.MdbCommand.VEND_FAILURE:
                self.send_ack()
                logger.debug("Got VEND FAILURE.")
                self.reader_state = Cashless.State.ENABLED
                self.event_queue.put(protocol.MdbCommandEvent(Cashless.MdbCommand.VEND_FAILURE))

            elif cmd == Cashless.MdbCommand.VEND_SESSION_COMPLETE:
                self.send_ack()
                logger.debug("Got VEND SESSION COMPLETE.")
                self.event_queue.put(protocol.MdbCommandEvent(Cashless.MdbCommand.VEND_SESSION_COMPLETE))
                self.reader_state = Cashless.State.ENABLED
                self.end_session()

            elif cmd == Cashless.MdbCommand.READER_DISABLE:
                self.send_ack()
                logger.debug("Got CSH READER DISABLE.")
                self.reader_state = Cashless.State.DISABLED
                self.event_queue.put(protocol.MdbCommandEvent(Cashless.MdbCommand.READER_DISABLE))

            elif cmd == Cashless.MdbCommand.READER_ENABLE:
                self.send_ack()
                logger.debug("Got CSH READER ENABLE")
                self.reader_state = Cashless.State.ENABLED
                self.event_queue.put(protocol.MdbCommandEvent(Cashless.MdbCommand.READER_ENABLE))

            elif cmd == Cashless.MdbCommand.READER_CANCEL:
                self.cancelled()
                logger.debug("Got CSH READER CANCEL")
                self.reader_state = Cashless.State.ENABLED
                self.event_queue.put(protocol.MdbCommandEvent(Cashless.MdbCommand.READER_CANCEL))

            elif cmd == Cashless.MdbCommand.EXPANSION_REQUEST_ID:
                manufacturer_code = helpers.get_ascii_from_hex(raw_cmd[4:10])
                serial_number = helpers.get_ascii_from_hex(raw_cmd[10:34])
                model_number = helpers.get_ascii_from_hex(raw_cmd[34:58])
                software_version = helpers.hex_to_int(raw_cmd[58:62])
                logger.debug(
                    f"Got CSH EXPANSION. Mfr: {manufacturer_code} Serial: {serial_number} Model: {model_number} Software Version: {software_version}")

                self.event_queue.put(Cashless.ExpansionRequestIdCommandEvent(manufacturer_code, serial_number, model_number,
                                                                             software_version))

            else:
                if self.enable_unsupported_commands:
                    logger.debug("Received unknown mdb command: " + raw_cmd)
                    self.event_queue.put(protocol.UnknownCommandEvent(raw_cmd))
                else:
                    logger.debug("Received unknown mdb command: " + raw_cmd)

        except ValueError as e:
            # TODO: remove after development
            if raw_cmd not in ["00", "0B", "08"]:
                logger.warning(f"Error parsing command ({raw_cmd}): {e}")
