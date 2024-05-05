from queue import Queue

import pymultidropbus

commands_queue = Queue()
mdb = pymultidropbus.MDB(commands_queue)

while True:
    # get the next command from the queue
    command = commands_queue.get()
    # command = commands_queue.get_nowait() # non-blocking version if you want to do other stuff while waiting
    if command:
        print(command)
    # mark the command as done
    commands_queue.task_done()
