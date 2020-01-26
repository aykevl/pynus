# Python NUS console

A simple NUS (Nordic UART Service) console to connect to the UART-over-BLE for
Nordic chips. It uses BlueZ over DBus, and probably requires at least [BlueZ
5.30](http://www.bluez.org/release-of-bluez-5-30/) or rather [BlueZ
5.42](http://www.bluez.org/release-of-bluez-5-42/) (tested on version 5.43 in
Debian).

Simply run the script (using Python 3 - Python 2 is not supported!) and it
by default connects to the first NUS console it can find. Exit using
`Ctrl-X`.

Address to the device or name can be defined via arguments in order to directly
connect to the NUS device.


If the `reconnect` argument is given it will perform a automatic reconnect when peer has disconnected. This means that `Ctrl-D` within MicroPython will trigger a soft reset  which drops the connection, and connect to the device again once it is up.

## Usage

The `pynus.py` works standalone, and can also give verbose prints in the terminal to show the progress of where it is:

```
./pynus.py -r -v
Connecting to mpus (F4:9C:FC:89:A7:3F)...
Connected to mpus (F4:9C:FC:89:A7:3F).
Resolving services...
Exit console using Ctrl-X.
(*** ENTER IS PRESSED ***)
>>>
(*** CTRL+B IS PRESSED ***)
MicroPython v1.11-668-ge65941b6f-dirty on 2020-01-26; PCA10056 with NRF52840
Type "help()" for more information.
>>> Disonnected from mpus (F4:9C:FC:89:A7:3F).
Reconnecting to mpus (F4:9C:FC:89:A7:3F)...
Connected to mpus (F4:9C:FC:89:A7:3F).
(*** ENTER IS PRESSED ***)
>>> 
```

## Using pynus.py in conjunction with putty, screen, rshell, ampy and friends

Supplied is a script called `run_pty.sh` which will wrap the `pynus.py` with no arguments (silent mode), and create a `/dev/pty/X` device which can be used as a normal serial port on Linux. 

Example:
```
./run_pty.sh 
2020/01/26 22:19:31 socat[4686] N PTY is /dev/pts/4
2020/01/26 22:19:31 socat[4686] N forking off child, using pty for reading and writing
2020/01/26 22:19:31 socat[4686] N forked off child process 4687
2020/01/26 22:19:31 socat[4686] N forked off child process 4687
2020/01/26 22:19:31 socat[4686] N starting data transfer loop with FDs [5,5] and [7,7]
2020/01/26 22:19:31 socat[4687] N execvp'ing "./pynus.py"
```

This shows that the PTY to connect to will be `/dev/pts/4`.

Now, connect your favorite serial terminal program to it:
```
screen /dev/pts/4
```
Or,
```
rshell -p /dev/pts/4
```

## TODO

  * Either use a real library (e.g.
    [gatt-python](https://github.com/getsenic/gatt-python) looks promising), or
    extract the important bits to a new library.

## License

This project is licensed under the MIT license, just like MicroPython.
