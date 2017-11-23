#!/usr/bin/python3

import tealblue
import termios
import sys
import tty

NUS_SERVICE_UUID      = '6e400001-b5a3-f393-e0a9-e50e24dcca9e'
NUS_CHARACTERISTIC_RX = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'
NUS_CHARACTERISTIC_TX = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'

def find_device(adapter):
    with adapter.scan() as scanner:
        for device in scanner:
            if '6e400001-b5a3-f393-e0a9-e50e24dcca9e' in device.UUIDs:
                return device

def run_terminal(tx):
    old_mode = termios.tcgetattr(sys.stdin.fileno())
    try:
        tty.setraw(sys.stdin.fileno())
        while True:
            s = sys.stdin.buffer.read1(20)
            s = s.replace(b'\n', b'\r')
            if s == b'\x18': # Ctrl-X: exit terminal
                return
            tx.write(s)
    except tealblue.NotConnectedError:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_mode)
        print('lost connection', file=sys.stderr)
        return
    finally:
        # restore old terminal mode
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_mode)

def on_notify(characteristic, value):
    data = bytes(value).replace(b'\n', b'\r\n').decode('utf-8')
    sys.stdout.write(data)
    sys.stdout.flush()

def nus():
    adapter = tealblue.TealBlue().find_adapter()

    device = find_device(adapter)
    if not device.connected:
        print('Connecting to %s (%s)...' % (device.name, device.address))
        device.connect()
    else:
        print('Connected to %s (%s).' % (device.name, device.address))

    if not device.services_resolved:
        print('Resolving services...')
        device.resolve_services()
    print('Exit console using Ctrl-X.')

    service = device.services[NUS_SERVICE_UUID]
    rx = service.characteristics[NUS_CHARACTERISTIC_RX]
    tx = service.characteristics[NUS_CHARACTERISTIC_TX]

    rx.start_notify()
    rx.on_notify = on_notify

    run_terminal(tx)

if __name__ == '__main__':
    tealblue.glib_mainloop_wrapper(nus)
