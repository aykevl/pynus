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
        self._device_props = None
        self._rx = None
        self._tx = None

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self._loop = GLib.MainLoop()
        thread_mainloop = threading.Thread(target=self._loop.run, daemon=True)
        thread_mainloop.start()

        self._bus = dbus.SystemBus()
        self._bluez = dbus.Interface(self._bus.get_object("org.bluez", "/"),
                                     "org.freedesktop.DBus.ObjectManager")

        self.find_nus_device()

        if not self._device_props['Connected']:
            print('Connecting to %s (%s)...' % (self._device_props['Name'], self._device_props['Address']), end='')
            self._device.Connect()
            print(' ok')
        else:
            print('Connected to %s (%s).' % (self._device_props['Name'], self._device_props['Address']))

        def prop_changed(iface, changed_props, invalidated_props):
            self.on_prop_changed(iface, changed_props)

        device_props = dbus.Interface(self._device, 'org.freedesktop.DBus.Properties')
        device_props.connect_to_signal('PropertiesChanged', prop_changed)

        self._thread_tx = threading.Thread(target=self.run_tx, daemon=True)
        self._thread_tx.start()

        rx_props = dbus.Interface(self._rx, 'org.freedesktop.DBus.Properties')
        rx_props.connect_to_signal('PropertiesChanged', prop_changed)
        self._rx.StartNotify()

        #print('Disconnecting...')
        #device.Disconnect()

    def run(self):
        self._loop.run()

    def on_prop_changed(self, iface, changed_props):
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

    def find_nus_device(self):
        objects = self._bluez.GetManagedObjects()
        for path in objects.keys():
            interface = objects[path]
            if 'org.bluez.Device1' not in interface:
                continue
            properties = interface['org.bluez.Device1']
            if NUS_SERVICE_UUID not in properties['UUIDs']:
                continue

            self._device_props = properties

            self._device = dbus.Interface(self._bus.get_object('org.bluez', path), 'org.bluez.Device1')
            service_path = self.find_nus_service(objects)
            self.find_nus_characteristics(objects, service_path)

            # TODO if there is more than one, let the user choose?

        # TODO do scan if no device can be found

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

    def find_nus_characteristics(self, objects, service_path):
        for path in objects.keys():
            if not path.startswith(service_path):
                continue
            if 'org.bluez.GattCharacteristic1' not in objects[path]:
                continue
            properties = objects[path]['org.bluez.GattCharacteristic1']
            obj = dbus.Interface(self._bus.get_object('org.bluez', path), 'org.bluez.GattCharacteristic1')
            if properties['UUID'] == NUS_CHARACTERISTIC_RX:
                self._rx = obj
            elif properties['UUID'] == NUS_CHARACTERISTIC_TX:
                self._tx = obj

    def run_tx(self):
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
                self._tx.WriteValue(s, {})
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
