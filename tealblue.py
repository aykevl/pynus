#!/usr/bin/python3

import dbus
import dbus.mainloop.glib
from gi.repository import GLib
import threading
import queue
import traceback
import time

class NotConnectedError(Exception):
    pass

class TealBlue:
    def __init__(self):
        self._bus = dbus.SystemBus()
        self._bluez = dbus.Interface(self._bus.get_object("org.bluez", "/"),
                                     "org.freedesktop.DBus.ObjectManager")

    def find_adapter(self):
        # find the first adapter
        objects = self._bluez.GetManagedObjects()
        for path in sorted(objects.keys()):
            interfaces = objects[path]
            if 'org.bluez.Adapter1' not in interfaces:
                continue
            properties = interfaces['org.bluez.Adapter1']
            return Adapter(self, path, properties)
        return None # no adapter found

class Adapter:
    def __init__(self, teal, path, properties):
        self._teal = teal
        self._path = path
        self._properties = properties
        self._object = dbus.Interface(teal._bus.get_object('org.bluez', path), 'org.bluez.Adapter1')

    def __repr__(self):
        return '<tealblue.Adapter address=%s>' % (self._properties['Address'])

    def devices(self):
        '''
        Returns the devices that BlueZ has discovered.
        '''
        objects = self._teal._bluez.GetManagedObjects()
        for path in sorted(objects.keys()):
            interfaces = objects[path]
            if 'org.bluez.Device1' not in interfaces:
                continue
            properties = interfaces['org.bluez.Device1']
            yield Device(self._teal, path, properties)

    def scan(self):
        return Scanner(self._teal, self, self.devices())

class Scanner:
    def __init__(self, teal, adapter, initial_devices):
        self._teal = teal
        self._adapter = adapter
        self._was_discovering = adapter._properties['Discovering'] # TODO get current value, or watch property changes
        self._queue = queue.Queue()
        for device in initial_devices:
            self._queue.put(device)

        def new_device(path, interfaces):
            if not 'org.bluez.Device1' in interfaces:
                return
            if not path.startswith(self._adapter._path+'/'):
                return
            properties = interfaces['org.bluez.Device1']
            self._queue.put(Device(self._teal, path, interfaces['org.bluez.Device1']))

        self._signal_receiver = self._teal._bus.add_signal_receiver(new_device, dbus_interface='org.freedesktop.DBus.ObjectManager', signal_name='InterfacesAdded')
        if not self._was_discovering:
            self._adapter._object.StartDiscovery()

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        if not self._was_discovering:
            self._adapter._object.StopDiscovery()
        self._signal_receiver.remove()

    def __iter__(self):
        return self

    def __next__(self):
        return self._queue.get()

class Device:
    def __init__(self, teal, path, properties):
        self._teal = teal
        self._path = path
        self._properties = properties
        self._services_resolved = threading.Event()
        self._services = None

        if properties['ServicesResolved']:
            self._services_resolved.set()

        # Listen to device events (connect, disconnect, ServicesResolved, ...)
        self._device = dbus.Interface(teal._bus.get_object('org.bluez', path), 'org.bluez.Device1')
        self._device_props = dbus.Interface(self._device, 'org.freedesktop.DBus.Properties')
        self._signal_receiver = self._device_props.connect_to_signal('PropertiesChanged', lambda itf, ch, inv: self._on_prop_changed(itf, ch, inv))

    def __del__(self):
        self._signal_receiver.remove()

    def __repr__(self):
        return '<tealblue.Device address=%s name=%r>' % (self.address, self.name)

    def _on_prop_changed(self, properties, changed_props, invalidated_props):
        for key, value in changed_props.items():
            self._properties[key] = value

        if 'ServicesResolved' in changed_props:
            if changed_props['ServicesResolved']:
                self._services_resolved.set()
            else:
                self._services_resolved.clear()

    def _wait_for_discovery(self):
        # wait until ServicesResolved is True
        self._services_resolved.wait()

    def connect(self):
        self._device.Connect()

    def resolve_services(self):
        self._services_resolved.wait()

    @property
    def services(self):
        if not self._services_resolved.is_set():
            return None
        if self._services is None:
            self._services = {}
            objects = self._teal._bluez.GetManagedObjects()
            for path in sorted(objects.keys()):
                if not path.startswith(self._path+'/'):
                    continue
                if 'org.bluez.GattService1' in objects[path]:
                    properties = objects[path]['org.bluez.GattService1']
                    service = Service(self._teal, self, path, properties)
                    self._services[service.uuid] = service
                elif 'org.bluez.GattCharacteristic1' in objects[path]:
                    properties = objects[path]['org.bluez.GattCharacteristic1']
                    characterstic = Characteristic(self._teal, self, path, properties)
                    for service in self._services.values():
                        if properties['Service'] == service._path:
                            service.characteristics[characterstic.uuid] = characterstic
        return self._services

    @property
    def connected(self):
        return bool(self._properties['Connected'])

    @property
    def services_resolved(self):
        return bool(self._properties['ServicesResolved'])

    @property
    def UUIDs(self):
        return [str(s) for s in self._properties['UUIDs']]

    @property
    def address(self):
        return str(self._properties['Address'])

    @property
    def name(self):
        if not 'Name' in self._properties:
            return None
        return str(self._properties['Name'])

    @property
    def alias(self):
        if not 'Alias' in self._properties:
            return None
        return str(self._properties['Alias'])

class Service:
    def __init__(self, teal, device, path, properties):
        self._device = device
        self._teal = teal
        self._path = path
        self._properties = properties
        self.characteristics = {}

    def __repr__(self):
        return '<tealblue.Service device=%s uuid=%s>' % (self._device.address, self.uuid)

    @property
    def uuid(self):
        return str(self._properties['UUID'])

class Characteristic:
    def __init__(self, teal, device, path, properties):
        self._device = device
        self._teal = teal
        self._path = path
        self._properties = properties

        self.on_notify = None

        self._char = dbus.Interface(teal._bus.get_object('org.bluez', path), 'org.bluez.GattCharacteristic1')
        char_props = dbus.Interface(self._char, 'org.freedesktop.DBus.Properties')
        self._signal_receiver = char_props.connect_to_signal('PropertiesChanged', lambda itf, ch, inv: self._on_prop_changed(itf, ch, inv))

    def __repr__(self):
        return '<tealblue.Characteristic device=%s uuid=%s>' % (self._device.address, self.uuid)

    def __del__(self):
        self._signal_receiver.remove()

    def _on_prop_changed(self, properties, changed_props, invalidated_props):
        for key, value in changed_props.items():
            self._properties[key] = value

        if 'Value' in changed_props and self.on_notify is not None:
            self.on_notify(self, changed_props['Value'])

    def write(self, value):
        start = time.time()
        try:
            self._char.WriteValue(value, {})
        except dbus.DBusException as e:
            if e.get_dbus_name() == 'org.bluez.Error.Failed' and e.get_dbus_message() == 'Not connected':
                raise NotConnectedError()
            else:
                raise # some other error

        # Workaround: if the write took very long, it is possible the connection
        # broke (without causing an exception). So check whether we are still
        # connected.
        # I think this is a bug in BlueZ.
        if time.time() - start > 0.5:
            if not self._device._device_props.Get('org.bluez.Device1', 'Connected'):
                raise NotConnectedError()

    def start_notify(self):
        self._char.StartNotify()

    @property
    def uuid(self):
        return str(self._properties['UUID'])

def glib_mainloop_wrapper(callback):
    loop = GLib.MainLoop()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    def callback_wrapper():
        try:
            callback()
        except:
            traceback.print_exc()
        finally:
            loop.quit()
    threading.Thread(target=callback_wrapper, daemon=True).start()
    loop.run()


def test():
    adapter = TealBlue().find_adapter()
    print('Bluetooth adapter:', adapter)
    with adapter.scan() as scanner:
        for device in scanner:
            print('Device:', device)
            for uuid in device.UUIDs:
                print('    UUID:', uuid)


if __name__ == '__main__':
    glib_mainloop_wrapper(test)
