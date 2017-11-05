# Python NUS console

A simple NUS (Nordic UART Service) console to connect to the UART-over-BLE for
Nordic chips. It uses BlueZ over DBus, and probably requires at least [BlueZ
5.30](http://www.bluez.org/release-of-bluez-5-30/) or rather [BlueZ
5.42](http://www.bluez.org/release-of-bluez-5-42/) (tested on version 5.43 in
Debian).

Simply run the script (using Python 3 - Python 2 is not supported!) and it
automatically connects to the first NUS console it can find. Exit using
`Ctrl-X`.

Don't use `Ctrl-D` within MicroPython unless you must: it does a soft reset
which drops the connection. Detecting this is only partially implemented.

## TODO

  * Exit the console on a disconnect, and not with the first keypress after a
    disconnect.
  * Either use a real library (e.g.
    [gatt-python](https://github.com/getsenic/gatt-python) looks promising), or
    extract the important bits to a new library.

## License

This project is licensed under the MIT license, just like MicroPython.
