#!/usr/bin/python3

import tealblue
import termios
import sys
import tty
import logging
import argparse
import fcntl
import os

NUS_SERVICE_UUID      = '6e400001-b5a3-f393-e0a9-e50e24dcca9e'
NUS_CHARACTERISTIC_RX = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'
NUS_CHARACTERISTIC_TX = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'

EXIT_REASON_NONE = 0
EXIT_REASON_DISCONNECTED = 1
EXIT_REASON_QUIT = 2

disconnected = False

def trace(message):
    if args.verbose:
        sys.stdout.write(message + "\r\n")
    if args.logging:
        logging.info(message)

def scan_device(adapter, address="", name=""):
    with adapter.scan() as scanner:
        for device in scanner:
            if len(address) > 0:
                if address == device.address:
                    return device
            elif len(name) > 0:
                if name == device.name:
                    return device
            else:
                if NUS_SERVICE_UUID in device.UUIDs:
                    return device

def lookup_device(adapter, address="", name=""):
    for device in adapter.devices():
        if len(address) > 0:
            if address == device.address:
                return device
        elif len(name) > 0:
            if name == device.name:
                return device
        else:
            if NUS_SERVICE_UUID in device.UUIDs:
                return device

def list_devices(adapter):
    for device in adapter.devices():
        if NUS_SERVICE_UUID in device.UUIDs:
            sys.stdout.write(device.name + " - " + device.address + "\r\n")

def run_terminal(rx):
    global disconnected
    exit_reason = EXIT_REASON_NONE
    fileno = sys.stdin.fileno()
    old_mode = termios.tcgetattr(fileno)
    old_fl = fcntl.fcntl(fileno, fcntl.F_GETFL)
    try:
        tty.setraw(fileno)
        fcntl.fcntl(fileno, fcntl.F_SETFL, old_fl | os.O_NONBLOCK)
        while True and not disconnected:
            s = sys.stdin.buffer.read1(20)
            if s == b'\x18': # Ctrl-X: exit terminal
                exit_reason = EXIT_REASON_QUIT
                break
            elif s:
                rx.write(s)
    except tealblue.NotConnectedError:
        # restore old terminal mode
        termios.tcsetattr(fileno, termios.TCSADRAIN, old_mode)
        fcntl.fcntl(fileno, fcntl.F_SETFL, old_fl)
        trace('lost connection')
        exit_reason = EXIT_REASON_DISCONNECTED
    finally:
        # restore old terminal mode
        tty.setcbreak(fileno)
        termios.tcsetattr(fileno, termios.TCSADRAIN, old_mode)
        fcntl.fcntl(fileno, fcntl.F_SETFL, old_fl)

    return exit_reason

def on_notify(characteristic, value):
    data = bytes(value).decode('utf-8')
    sys.stdout.write(data)
    sys.stdout.flush()

def on_event(device, event):
    global disconnected
    if event == device.EVENT_CONNECTED:
        trace('Connected to %s (%s).' % (device.name, device.address))
        disconnected = False
    elif event == device.EVENT_DISCONNECTED:
        trace('Disonnected from %s (%s).' % (device.name, device.address))
        disconnected = True

def nus():
    global disconnected
    quit = False
    adapter = tealblue.TealBlue().find_adapter()

    if args.list:
        list_devices(adapter)
        return

    # TODO: notify if scanning
    device = lookup_device(adapter, args.address, args.name)
    if not device:
        trace('Scanning...')
        device = scan_device(adapter, args.address, args.name)

    device.on_event = on_event

    if not device.connected:
        trace('Connecting to %s (%s)...' % (device.name, device.address))
        device.connect()

    if not device.services_resolved:
        trace('Resolving services...')
        device.resolve_services()
    trace('Exit console using Ctrl-X.')

    service = device.services[NUS_SERVICE_UUID]
    rx = service.characteristics[NUS_CHARACTERISTIC_RX]
    tx = service.characteristics[NUS_CHARACTERISTIC_TX]

    tx.start_notify()
    tx.on_notify = on_notify

    while not quit:
        if not device.connected:
            trace('Reconnecting to %s (%s)...' % (device.name, device.address))
            device.connect()
        else:
            exit_reason = run_terminal(rx)
            if exit_reason == EXIT_REASON_QUIT:
                 quit = True
            else:
                if not args.reconnect and disconnected:
                    quit = True
                else:
                    quit = False
    if device.connected:
        device.disconnect()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('-a', '--address', default="",
                        help='address of the device to connect')
    parser.add_argument('-n', '--name', default="",
                        help='device name of the device to connect')
    parser.add_argument('-r', '--reconnect', default=False,
                        action='store_true',
                        help='automatic reconnect')
    parser.add_argument('--list', default=False,
                        action='store_true',
                        help='Print list of available devices. No other actions will be performed')
    parser.add_argument('-l', '--logging', default=False,
                        action='store_true',
                        help='enable logging to pynus.log')
    parser.add_argument('-v', '--verbose', default=False,
                        action='store_true',
                        help='verbose output log')
    args, unknown = parser.parse_known_args()

    if args.logging:
        logging.basicConfig(filename='pynus.log',level=logging.DEBUG)
    tealblue.glib_mainloop_wrapper(nus)
