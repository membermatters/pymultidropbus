import serial
import termios
import binascii

CMSPAR = 0x40000000

ser = serial.Serial('/dev/ttyAMA0', 9600, 8, timeout=1, parity=serial.PARITY_NONE)

def mode_bit_on():
    iflag,oflag,cflag,lflag,ispeed,ospeed,cc = termios.tcgetattr(ser)
    cflag |= termios.PARENB | CMSPAR | termios.PARODD
    termios.tcsetattr(ser, termios.TCSANOW, [iflag,oflag,cflag,lflag,ispeed,ospeed,cc])


def mode_bit_off():
    iflag,oflag,cflag,lflag,ispeed,ospeed,cc = termios.tcgetattr(ser)
    cflag |= termios.PARENB | CMSPAR
    cflag &= ~termios.PARENB
    termios.tcsetattr(ser, termios.TCSANOW, [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])

def get_chk(cmd):
    cmd_bytes = bytearray.fromhex(cmd)
    chk = 0
    for cmd_byte in cmd_bytes:
        chk += cmd_byte
    return chk % 16**2 # ignore the carry bit if it overflows

def send_cmd(cmd):
    chk = get_chk(cmd)
    ser.write(bytearray.fromhex(cmd))
    mode_bit_on()
    ser.write(chk)
    mode_bit_off()
    print("wrote: " + cmd + "{:X}".format(chk))

def recv_cmd(cmd):
    print("received: " + cmd)
    chk = get_chk(cmd[-2:])
    print("cmd: " + cmd[:-2])
    print("chk: " + "{:X}".format(chk))
    return cmd[:-2]

print("Connected to: ")
print(ser.name)

#send_cmd("010109720A02070D")
#send_cmd("0200010502000701020514FF")
#send_cmd("03FFFF01")

while True:
    cmd_raw = ser.read(size=32)
    cmd = cmd_raw.decode("ascii").strip('\x03\x02')
   
    if cmd:
        parsed = recv_cmd(cmd)
