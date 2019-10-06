#!/usr/bin/python3

import tealblue
import sys
import struct
import math
import threading
import time

DFU_SERVICE_UUID          = '67fc0001-83ae-f58c-f84b-ba72efb822f4'
DFU_CHARACTERISTIC_INFO   = '67fc0002-83ae-f58c-f84b-ba72efb822f4'
DFU_CHARACTERISTIC_CALL   = '67fc0003-83ae-f58c-f84b-ba72efb822f4'
DFU_CHARACTERISTIC_BUFFER = '67fc0004-83ae-f58c-f84b-ba72efb822f4'

COMMAND_RESET        = 0x01
COMMAND_ERASE_PAGE   = 0x02
COMMAND_WRITE_BUFFER = 0x03
COMMAND_ADD_BUFFER   = 0x04
COMMAND_PING         = 0x10
COMMAND_START        = 0x11

class DFUInfo:
    def __init__(self, data):
        info = struct.unpack('BBH4sHH', data)
        self.version    = info[0]
        self.page_size  = 2**info[1]
        self.flash_size = info[2] * self.page_size
        self.chip_id    = info[3].decode('utf-8')
        self.app_start  = info[4] * self.page_size
        self.app_size   = info[5] * self.page_size

    def get_page_number(self, address):
        page = address / self.page_size
        if math.floor(page) != math.ceil(page):
            raise ValueError('address not rounded to page')
        return int(page)

class Block:
    def __init__(self, address, data):
        self.address = address
        self.data = data

    def __len__(self):
        return len(self.data)

    def split_pages(self, pagesize):
        if len(self) <= pagesize:
            yield self
        else:
            address = self.address
            for i in range(0, len(self), pagesize):
                yield Block(address, self.data[i:i+pagesize])
                address += pagesize

def scan_device(adapter):
    with adapter.scan() as scanner:
        for device in scanner:
            print('found device %s (%s)' % (device.name, device.address))
            if DFU_SERVICE_UUID in device.UUIDs:
                return device

def lookup_device(adapter):
    for device in adapter.devices():
        if DFU_SERVICE_UUID in device.UUIDs:
            return device

class FirmwareUpdater:
    def __init__(self, command, arg):
        adapter = tealblue.TealBlue().find_adapter()

        self.device = lookup_device(adapter)
        if not self.device:
            print('Scanning...')
            self.device = scan_device(adapter)
        if not self.device.connected:
            print('Connecting to %s (%s)...' % (self.device.name, self.device.address))
            self.device.connect()
        else:
            print('Connected to %s (%s).' % (self.device.name, self.device.address))

        if not self.device.services_resolved:
            print('Resolving services...')
            self.device.resolve_services()

        service = self.device.services[DFU_SERVICE_UUID]
        self.char_info = service.characteristics[DFU_CHARACTERISTIC_INFO]
        self.char_call = service.characteristics[DFU_CHARACTERISTIC_CALL]
        self.char_buff = service.characteristics[DFU_CHARACTERISTIC_BUFFER]

        self.char_call.start_notify()
        self.char_call.on_notify = self.on_notify

        info_data = self.char_info.read()
        self.info = DFUInfo(bytes(info_data))
        self.print_info();

        self.call_event = threading.Event()

        if self.info.version != 1:
            print('Cannot flash this bootloader version.')
            sys.exit()

        if command is None or command == 'info':
            # info already printed
            pass
        elif command == 'reset':
            print('Command: reset')
            self.do_dfu_command(struct.pack('B', COMMAND_RESET))
        elif command == 'erase':
            # Erase the ISR vector of the app, so it won't start the app on
            # reset.
            self.do_dfu_command(struct.pack('BBH', COMMAND_ERASE_PAGE, 0, self.info.get_page_number(self.info.app_start)))
        elif command in ['flash', 'deploy', 'upload']:
            print('Command: flash hex file')
            self.write_hex(arg)
        elif command == 'ping':
            print('Command: ping')
            self.do_dfu_command(struct.pack('B', COMMAND_PING), wait_for_response=True)
        elif command == 'start':
            print('Command: start app')
            self.do_dfu_command(struct.pack('B', COMMAND_START))
        elif command == 'disconnect':
            print('Disconnecting...')
            self.device.disconnect()
        else:
            print('Unknown command:', command)
            help()

    def print_info(self):
        print('DFU version:        ', self.info.version)
        print('Chip ID:            ', self.info.chip_id)
        print('Page size:          ', self.info.page_size)
        print('Total flash size:    %skB' % (self.info.flash_size / 1024))
        print('App start address:  ', hex(self.info.app_start))
        print('App size:            %skB' % (self.info.app_size / 1024))
        print('Fast transport:      %s' % 'yes' if self.char_buff else 'no')

    def do_dfu_command(self, cmd, wait_for_response=False):
        self.do_dfu_write(self.char_call, cmd)

        if wait_for_response:
            self.wait_for_response()

    def do_dfu_write(self, char, value):
        try:
            char.write(value)
        except tealblue.NotConnectedError:
            print('Reconnecting...')
            self.device.connect()
            # This may throw the same error.
            char.write(value)

    def wait_for_response(self):
        self.call_event.wait()
        self.call_event.clear()
        if self.call_response[0] != 0:
            raise ValueError('DFU command returned non-zero')

    def on_notify(self, characteristic, value):
        self.call_response = value
        if self.call_event.is_set():
            # This is not a true safety check as there is a race condition,
            # but it will help discover race conditions if they exist.
            raise ValueError('call event is set while entering event')
        self.call_event.set()

    def write_hex(self, path):
        start = time.time()
        total_size = 0
        for block in self.read_hex(path):
            total_size += len(block)
            for page in block.split_pages(self.info.page_size):
                page_number = self.info.get_page_number(page.address)
                print('writing page %d at address 0x%x with size %d' %(page_number, page.address, len(page)))

                # erase page
                self.do_dfu_command(struct.pack('BBH', COMMAND_ERASE_PAGE, 0, page_number), wait_for_response=True)

                # fill the internal buffer
                if self.char_buff:
                    # high speed transfer possible
                    for i in range(0, len(page), 20):
                        self.do_dfu_write(self.char_buff, page.data[i:i+20])
                else:
                    # fall back to low speed on the same characteristic
                    for i in range(0, len(page), 16):
                        self.do_dfu_command(struct.pack('BBH16s', COMMAND_ADD_BUFFER, 0, 0, page.data[i:i+16]))

                # write this page to flash
                self.do_dfu_command(struct.pack('BBHH', COMMAND_WRITE_BUFFER, 0, page_number, int(len(page)/4)), wait_for_response=True)
        duration = time.time() - start
        print('done, transfer took %.1fs (%.1fkB/s)' % (duration, total_size / duration / 1024))

    def read_hex(self, path):
        # Resources:
        # https://en.wikipedia.org/wiki/Intel_HEX
        # http://infocenter.arm.com/help/index.jsp?topic=/com.arm.doc.faqs/ka9903.html
        block = None
        base_address = 0
        for line in open(path, 'r'):
            line = line.strip()
            if not line:
                continue
            if not line.startswith(':'):
                raise ValueError('Intel hex files should start with a colon')
            line = line[1:]
            line = bytes.fromhex(line)
            line = line[:-1] # drop checksum
            datalen, address, record_type = struct.unpack('>BHB', line[:4])
            data = line[4:]
            if len(data) != datalen:
                raise ValueError('data length doesn\'t match data length in record')
            if record_type == 0: # Data
                if block is None:
                    block = Block(base_address + address, data)
                else:
                    if block.address + len(block) != base_address + address:
                        # address changed, create a new block
                        yield block
                        block = Block(base_address + address, data)
                    else:
                        block.data += data
            elif record_type == 1: # EOF
                # Ignore, this should be the last line anyway
                pass
            elif record_type == 2: # Extended Segment Address
                if block is not None:
                    yield block
                    block = None
                base_address = struct.unpack('>H', data)[0] * 16
            elif record_type == 3: # Start Segment Address
                # Ignore this one, but set the base_address to make sure we
                # don't accidentally read more blocks.
                # No idea why this record even exists, it's only relevant for
                # ancient Intel processors. It appears to contain the start
                # address of the .text segment.
                base_address = None
            else:
                raise ValueError('unknown record type: %d' % record_type)

        if block is not None:
            yield block

def help():
    print('Available command-line arguments:')
    print('help            show this message')
    print('info            retrieve chip/size etc. from DFU')
    print('flash <path>    flash the given Intel .hex file')
    print('reset           reset chip (will disconnect!)')
    print('disconnect      disconnect the chip')
    print('erase           DEBUG: erase first page of application')
    print('ping            DEBUG: see whether the device is still alive')
    print('start           DEBUG: try to start the app (may fail)')


def main():
    command = None
    arg = None
    if len(sys.argv) > 1:
        command = sys.argv[1]
    if len(sys.argv) > 2:
        arg = sys.argv[2]
    if command == 'help':
        help()
        return
    tealblue.glib_mainloop_wrapper(FirmwareUpdater, (command, arg))

if __name__ == '__main__':
    main()
