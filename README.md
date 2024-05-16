# pymultidropbus

A Python library that implements a cashless MDB peripheral over UART. This is for integrating an external payment system
with an MDB enabled vending machine. _This library will not talk to an MDB enabled credit card reader - it pretends to
be one._

This library is not production ready, and is a continual work in progress. Contributions are welcome, but we will not be
accepting feature requests at this time.

## Software Requirements

This library should be compatible with most Linux Python environments that support the `pyserial` library, and any
serial hardware that supports setting a sticky parity bit.

However, this library is currently only developed for and supported on a Raspberry Pi.

### Install Dependencies

Install the required Python dependencies by running the following command:

`pip3 install -r requirements.txt`

## Hardware Requirements

Please note that a multicore raspberry pi with an entire core dedicated to your MDB application is highly recommended.
Linux is not a realtime operating system, and the MDB protocol has strict timing requirements which occasionally causes
issues. If your use case is not public facing or doesn't need high reliability, you may not need to worry about this.

Read more about dedicating one of your cores to a single
process [here](https://floating.io/2023/04/raspberry-pi-in-real-time/), [here](https://stackoverflow.com/questions/13583146/whole-one-core-dedicated-to-single-process)
and [here](https://stackoverflow.com/questions/74175771/how-to-run-t-threads-to-a-specific-cpu).