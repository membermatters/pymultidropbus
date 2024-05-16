from queue import Queue

import pymultidropbus

# This will set up a queue that can be used to receive and process commands from the MDB bus
commands_queue = Queue()

# Open a connection to the MDB bus via the specified serial port (which should have appropriate isolation and
# level shifting to protect your device from the bus's potentially damaging high signal levels).
mdb = pymultidropbus.MDB(commands_queue, "/dev/ttyAMA0")

while True:
    # Loop continuously and get the next command from the queue
    command = commands_queue.get()
    # command = commands_queue.get_nowait() # non-blocking version if you want to do other stuff while waiting
    if command:
        print(command)
    # mark the command as done
    commands_queue.task_done()

    # If you want an example of a full cashless device implementation, check out this repo:
    # https://github.com/membermatters/mm-mdb
    # It uses this library, and implements all the events necessary to interact with a vending machine and pretend
    # to be a cashless device. It's a great starting point for building your own cashless device.
