import termios
import time
from struct import pack

import serial

CMSPAR = 0x40000000

ser = serial.Serial(
    "/dev/ttyAMA0", 9600, 8, serial.PARITY_SPACE, timeout=0.01
)


def wait_for_output_buffer_to_clear(command):
    # not ideal, but there is no way to reliably check if the output
    # buffer has finished writing, and we MUST wait until all the data
    # bytes are out before toggling the mode bit. It takes approx 1.25ms
    # to write 1 byte at 9600 baud, so we wait 1.25ms per byte.

    delay = (len(command) / 1000) * 1.25
    time.sleep(delay)
    return delay


def mode_bit_enable_mark():
    iflag,oflag,cflag,lflag,ispeed,ospeed,cc = termios.tcgetattr(ser)
    iflag |= termios.PARMRK | termios.INPCK
    iflag &= ~termios.IGNPAR
    termios.tcsetattr(ser, termios.TCSANOW, [iflag,oflag,cflag,lflag,ispeed,ospeed,cc])


def mode_bit_off():
    iflag,oflag,cflag,lflag,ispeed,ospeed,cc = termios.tcgetattr(ser)
    cflag |= termios.PARENB | CMSPAR
    cflag &= ~termios.PARODD
    termios.tcsetattr(ser, termios.TCSANOW, [iflag,oflag,cflag,lflag,ispeed,ospeed,cc])


def mode_bit_on():
    iflag,oflag,cflag,lflag,ispeed,ospeed,cc = termios.tcgetattr(ser)
    cflag |= termios.PARENB | CMSPAR | termios.PARODD
    termios.tcsetattr(ser, termios.TCSANOW, [iflag,oflag,cflag,lflag,ispeed,ospeed,cc])


def get_chk(command):
    chk = 0
    for cmd_byte in bytearray.fromhex(command):
        chk += cmd_byte
    return chk % 16**2  # ignore the carry bit if it overflows


def get_ascii_from_hex(hex_string):
    return bytearray.fromhex(hex_string).decode()


def hex_to_int(hex_string):
    return int(hex_string, 16)


def send_ack():
    mode_bit_on()
    ser.write(bytearray.fromhex("00"))
    mode_bit_off()
    print("Sent ACK")


def send_cmd(command_string):
    command_string = command_string.replace(" ", "")
    check_byte = get_chk(command_string)
    command = bytearray.fromhex(command_string)
    command_chk_byte = pack("B", check_byte)

    # let's write all our data bytes and wait for them to send
    for byte in command:
        ser.write(pack("B", byte))
    wait_for_output_buffer_to_clear(command)

    # now toggle the mode bit and write the chk byte
    mode_bit_on()
    ser.write(command_chk_byte)
    wait_for_output_buffer_to_clear(command_chk_byte)
    mode_bit_off()

    #print("wrote cmd: " + command_string + " {:02X}".format(check_byte))


def parse_cmd():
    command = ser.read(size=1).hex().upper()

    if command in ["00", "AA", "FF"]:
        # return straight away, these special commands don't have a checksum
        return command

    full_command = command
    while True:
        if len(full_command) > 36*2:
            print("WARN: command too long, discarding: " + full_command)
            ser.reset_input_buffer()
            return ""
        new_byte = ser.read(size=1).hex().upper()
        full_command_checksum = get_chk(full_command)
        new_byte_checksum = get_chk(new_byte)

        if new_byte_checksum == full_command_checksum:
            # we're at the end of the data block so return it
            return full_command
        else:
            full_command += new_byte


print("Connected to: ")
print(ser.name)
mode_bit_enable_mark()

reader_state = "inactive"

# send_cmd("02 32 02 32 42 4D 53 20 20 20 20 20 20 20 20 20 20 20 20 2E") # display BMS for 5 seconds?

while True:
    cmd_raw = ser.read(size=2).hex().upper()

    # this is the start of a new address byte
    if cmd_raw == "FF00":
        cmd = parse_cmd()
        print()

        if cmd == "00":
            print("Got ACK")

        elif cmd == "AA":
            print("Got RET :(")

        elif cmd == "FF":
            print("Got NACK")

        elif cmd == "08":
            print("Got CC RESET")

        elif cmd == "0B":
            print("Got CC POLL")

        elif cmd == "30":
            print("Got BV RESET")

        elif cmd == "33":
            print("Got BV POLL")

        elif cmd == "10":
            print("Got CSH RESET")
            reader_state = "inactive"

            send_ack()

        elif cmd[:4] == "1100":
            print("Got CSH SETUP Config Data")
            vmc_feature_level = hex_to_int(cmd[4:6])
            columns_on_display = hex_to_int(cmd[6:8])
            rows_on_display = hex_to_int(cmd[8:10])
            display_type = hex_to_int(cmd[10:12])
            print(f"VMC feature level: {vmc_feature_level} Columns on display: {columns_on_display} "
                  f"Rows on display: {rows_on_display} Display type: {display_type}")

            reader_state = "disabled"

            send_cmd("01 01 10 36 0A 02 07 0D")  # reader config data

        elif cmd[:4] == "1101":
            print("Got CSH SETUP Min/Max Prices ")
            max_price = hex_to_int(cmd[4:8]) / 10
            min_price = hex_to_int(cmd[8:12]) / 10
            print(f"Min price: ${min_price} Max price: ${max_price}")
            send_ack()

        elif cmd == "12":
            print("Got CSH POLL 12")

            if reader_state == "inactive":
                send_cmd("00")  # JUST RESET
            else:
                send_ack()

        elif cmd[:4] == "1300":
            print("Got VEND REQUEST")
            item_price = hex_to_int(cmd[4:8]) / 10
            item_number = None if hex_to_int(cmd[8:12]) == 0xFFFF else hex_to_int(cmd[8:12])
            print(f"Item price: ${item_price} Item number: {item_number}")

            approved = True
            amount_charged = 25 # scale up by ten
            amount_charged = f"{amount_charged:x}"

            if approved:
                send_cmd("05" + amount_charged)
            else:
                send_cmd("06")

        elif cmd[:4] == "1301":
            print("Got VEND CANCEL REQUEST")
            send_cmd("06")

        elif cmd[:4] == "1302":
            print("Got VEND SUCCESS")
            item_number = None if hex_to_int(cmd[4:8]) == 0xFFFF else hex_to_int(cmd[4:8])
            print(f"Item number: {item_number}")

            send_ack()

        elif cmd[:4] == "1303":
            print("Got VEND FAILURE")

            refund_success = True
            # TODO: refund the customer

            if refund_success:
                send_ack()
            else:
                # TODO: send MALFUNCTION ERROR code 1100yyyy
                send_cmd("")

        elif cmd[:4] == "1304":
            print("Got VEND SESSION COMPLETE")
            send_cmd("07")

        elif cmd[:4] == "1304":
            print("Got CASH SALE")
            item_price = hex_to_int(cmd[4:8]) / 10
            item_number = None if hex_to_int(cmd[8:12]) == 0xFFFF else hex_to_int(cmd[8:12])
            print(f"Item price: ${item_price} Item number: {item_number}")

            send_ack()

        elif cmd[:4] == "1400":
            print("Got CSH READER DISABLE")
            reader_state = "disabled"

            send_ack()

        elif cmd[:4] == "1401":
            print("Got CSH READER ENABLE")
            reader_state = "enabled"

            send_ack()

        elif cmd[:4] == "1402":
            print("Got CSH READER CANCEL")

            send_cmd("08")

        elif cmd[:4] == "1700":
            print("Got CSH EXPANSION ")
            manufacturer_code = get_ascii_from_hex(cmd[4:10])
            serial_number = get_ascii_from_hex(cmd[10:34])
            model_number = get_ascii_from_hex(cmd[34:58])
            software_version = hex_to_int(cmd[58:62])

            print(f"Manufacturer code: {manufacturer_code} Serial number: {serial_number} Model number: {model_number}"
                  f" Software version: {software_version}")

            # reader peripheral id data
            send_cmd("09 42 4D 53 30 30 30 30 30 30 30 30 30 30 30 31 30 30 30 30 30 30 30 30 30 30 30 31 01 01")

        else:
            print("WARNING: received unknown cmd: " + cmd)

    elif cmd_raw:
        print("WARNING: received non address bytes (probably corrupt data): " + cmd_raw)
