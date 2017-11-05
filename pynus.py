#!/usr/bin/python3

import sys
import termios
import select
import tty
import dbus
import dbus.mainloop.glib
from gi.repository import GLib
import threading

NUS_SERVICE_UUID      = '6e400001-b5a3-f393-e0a9-e50e24dcca9e'
NUS_CHARACTERISTIC_RX = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'
NUS_CHARACTERISTIC_TX = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'

class Console:
    def __init__(self):
        self._device = None

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self._loop = GLib.MainLoop()
        thread_mainloop = threading.Thread(target=self._loop.run, daemon=True)
        thread_mainloop.start()

        self._bus = dbus.SystemBus()
        self._bluez = dbus.Interface(self._bus.get_object("org.bluez", "/"),
                                     "org.freedesktop.DBus.ObjectManager")

        def new_device(path, interfaces):
            if not 'org.bluez.Device1' in interfaces:
                return
            self.on_new_device(path, interfaces['org.bluez.Device1'])

        # Does this system have a Bluetooth adapter?
        adapter_path = self.find_adapter()
        if adapter_path is None:
            print('It appears there is no Bluetooth adapter present.')
            sys.exit(1)

        device_path, interface = self.find_nus_device()
        if device_path is None:
            print('Cannot find device, starting discovery...')
            adapter = dbus.Interface(self._bus.get_object('org.bluez', adapter_path), 'org.bluez.Adapter1')
            adapter.StartDiscovery()
            print('Waiting for device...')
            self._bus.add_signal_receiver(new_device, dbus_interface='org.freedesktop.DBus.ObjectManager', signal_name='InterfacesAdded')
        else:
            self.on_device(interface, dbus.Interface(self._bus.get_object('org.bluez', device_path), 'org.bluez.Device1'))

    def on_device(self, interface, device):
        # Listen to device events (connect, disconnect, ...)
        device_props = dbus.Interface(device, 'org.freedesktop.DBus.Properties')
        device_props.connect_to_signal('PropertiesChanged',
                                       lambda itf, ch, inv: self.on_prop_changed(itf, ch, device=device, device_props=device_props))

        if not interface['Connected']:
            print('Connecting to %s (%s)... ' % (interface['Name'], interface['Address']), end='')
            sys.stdout.flush()
            device.Connect()
            print('ok')
        else:
            print('Connected to %s (%s).' % (interface['Name'], interface['Address']))

        if interface['ServicesResolved']:
            self.on_services(device, device_props)

    def on_services(self, device, props):
        if NUS_SERVICE_UUID not in props.Get('org.bluez.Device1', 'UUIDs'):
            print('  No NUS service.')
            return
        if self._device is not None:
            raise RuntimeError('on_services called twice')
        self._device = device

        rx, tx = self.find_nus_characteristics()

        # Start reading input from stdin.
        threading.Thread(target=self.run_tx, args=(tx,), daemon=True).start()

        # Start writing output to stdout.
        rx_props = dbus.Interface(rx, 'org.freedesktop.DBus.Properties')
        rx_props.connect_to_signal('PropertiesChanged', lambda itf, ch, inv: self.on_prop_changed(itf, ch))
        rx.StartNotify()

    def run(self):
        self._loop.run()

    def on_new_device(self, path, interface):
        # called when a device has been added (DBus event)
        device = dbus.Interface(self._bus.get_object('org.bluez', path), 'org.bluez.Device1')
        self.on_device(interface, device)

    def on_prop_changed(self, iface, changed_props, device=None, device_props=None):
        if iface == 'org.bluez.GattCharacteristic1':
            if 'Value' not in changed_props:
                return
            data = bytes(changed_props['Value']).replace(b'\n', b'\r\n').decode('utf-8')
            sys.stdout.write(data)
            sys.stdout.flush()
        elif iface == 'org.bluez.Device1':
            if 'Connected' in changed_props and not changed_props['Connected']:
                # TODO somehow cleanly shut down the process
                pass
            if 'ServicesResolved' in changed_props:
                if self._device is None:
                    self.on_services(device, device_props)

    def find_adapter(self):
        # find the first adapter
        objects = self._bluez.GetManagedObjects()
        for path in sorted(objects.keys()):
            interface = objects[path]
            if 'org.bluez.Adapter1' not in interface:
                continue
            return path

    def find_nus_device(self):
        objects = self._bluez.GetManagedObjects()
        for path in objects.keys():
            interfaces = objects[path]
            if 'org.bluez.Device1' not in interfaces:
                continue
            interface = interfaces['org.bluez.Device1']
            if NUS_SERVICE_UUID not in interface['UUIDs']:
                continue

            # TODO if there is more than one, let the user choose?
            return path, interface

        return None, None

    def find_nus_service(self, objects):
        for path in objects.keys():
            if not path.startswith(self._device.object_path):
                continue
            if 'org.bluez.GattService1' not in objects[path]:
                continue
            properties = objects[path]['org.bluez.GattService1']
            if properties['UUID'] != NUS_SERVICE_UUID:
                continue
            return path

    def find_nus_characteristics(self):
        objects = self._bluez.GetManagedObjects()
        service_path = self.find_nus_service(objects)
        rx = None
        tx = None
        for path in objects.keys():
            if not path.startswith(service_path):
                continue
            if 'org.bluez.GattCharacteristic1' not in objects[path]:
                continue
            properties = objects[path]['org.bluez.GattCharacteristic1']
            obj = dbus.Interface(self._bus.get_object('org.bluez', path), 'org.bluez.GattCharacteristic1')
            if properties['UUID'] == NUS_CHARACTERISTIC_RX:
                rx = obj
            elif properties['UUID'] == NUS_CHARACTERISTIC_TX:
                tx = obj
        return rx, tx

    def run_tx(self, tx):
        # save and restore the old terminal mode
        old_mode = termios.tcgetattr(sys.stdin.fileno())
        try:
            tty.setraw(sys.stdin.fileno())
            while True:
                s = sys.stdin.buffer.read1(20)
                s = s.replace(b'\n', b'\r')
                if s == b'\x18': # Ctrl-X: exit terminal
                    self._loop.quit()
                    sys.exit(0)
                tx.WriteValue(s, {})
        except dbus.DBusException as e:
            if e.get_dbus_name() == 'org.bluez.Error.Failed' and e.get_dbus_message() == 'Not connected':
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_mode)
                print('lost connection')
                self._loop.quit()
                sys.exit(1)
            else:
                raise # some other error
        finally:
            # restore old terminal mode
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_mode)


if __name__ == '__main__':
    Console().run()
