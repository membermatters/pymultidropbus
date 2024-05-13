import time


def get_chk(command: str):
    chk = 0
    for cmd_byte in bytearray.fromhex(command):
        chk += cmd_byte
    return chk % 16**2  # ignore the carry bit if it overflows


def wait_for_output_buffer_to_clear(command: bytes):
    # not ideal, but there is no way to reliably check if the output
    # buffer has finished writing, and we MUST wait until all the data
    # bytes are out before toggling the mode bit. It takes approx 1.25ms
    # to write 1 byte at 9600 baud, so we wait 1.25ms per byte.

    delay = (len(command) / 1000) * 1.25
    time.sleep(delay)
    return delay


def get_ascii_from_hex(hex_string: str):
    return bytearray.fromhex(hex_string).decode()


def hex_to_int(hex_string: str):
    return int(hex_string, 16)


def int_to_hex(int_value: int, padding: int = 2):
    return f"{int_value:x}".zfill(padding)


def cents_to_hex(int_value: int, padding: int = 4):
    # returns a hex formatted string with the right padding to send to the VMC
    return int_to_hex(int(int_value/10), padding)


def get_command_object(command: str, data: object = None):
    return {
        "command": command,
        "data": data
    }