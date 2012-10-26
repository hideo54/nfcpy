# -*- coding: latin-1 -*-
# -----------------------------------------------------------------------------
# Copyright 2009-2011 Stephen Tiedemann <stephen.tiedemann@googlemail.com>
#
# Licensed under the EUPL, Version 1.1 or - as soon they 
# will be approved by the European Commission - subsequent
# versions of the EUPL (the "Licence");
# You may not use this work except in compliance with the
# Licence.
# You may obtain a copy of the Licence at:
#
# http://www.osor.eu/eupl
#
# Unless required by applicable law or agreed to in
# writing, software distributed under the Licence is
# distributed on an "AS IS" basis,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied.
# See the Licence for the specific language governing
# permissions and limitations under the Licence.
# -----------------------------------------------------------------------------

import logging
log = logging.getLogger(__name__)

import tag

ndef_read_service = 11 # service code for NDEF reading
ndef_write_service = 9 # service code for NDEF writing

def trace(func):
    def traced_func(*args, **kwargs):
        _args = "{0}".format(args[1:]).strip("(),")
        if kwargs:
            _args = ', '.join([_args, "{0}".format(kwargs).strip("{}")])
        log.debug("{func}({args})".format(func=func.__name__, args=_args))
        return func(*args, **kwargs)
    return traced_func

class NdefAttributeData:
    def __init__(self, attr=16):
        attr = bytearray(attr)
        self.version = "{0}.{1}".format(attr[0] >> 4, attr[0] & 15)
        self.nbr = attr[1]
        self.nbw = attr[2]
        self.capacity = (attr[3] * 256 + attr[4]) * 16
        self.writing = bool(attr[9])
        self.writeable = bool(attr[10])
        self.length = attr[11]<<16 | attr[12]<<8 | attr[13]
        self.valid = sum(attr[0:14]) == attr[14] << 8 | attr[15]

    def __str__(self):
        attr = bytearray(16)
        vers = map(lambda x: int(x) & 15, self.version.split('.'))
        maxb = ((self.capacity + 15) // 16) & 0xffff
        attr[0] = vers[0] << 4 | vers[1]
        attr[1] = self.nbr
        attr[2] = self.nbw
        attr[3] = maxb >> 8
        attr[4] = maxb & 0xff
        attr[9] = 15 if self.writing else 0
        attr[10] = 1 if self.writeable else 0
        attr[11] = self.length >> 16 & 0xff
        attr[12] = self.length >> 8 & 0xff
        attr[13] = self.length & 0xff
        checksum = sum(attr[0:14])
        attr[14] = checksum >> 8
        attr[15] = checksum & 0xff
        return str(attr)
    
class NDEF(tag.NDEF):

    def __init__(self, tag):
        self.tag = tag
        self._attr = None
        if not sum(self.attr[0:14]) == self.attr[14] << 8 | self.attr[15]:
            log.error("checksum error in ndef attribute block")
            raise ValueError("checksum error in NDEF attribute block")
            
    @property
    def version(self):
        """The version of the NDEF mapping."""
        return "%d.%d" % (self.attr[0]>>4, self.attr[0]&0x0F)

    @property
    def capacity(self):
        """The maximum number of user bytes on the NDEF tag."""
        return (self.attr[3] * 256 + self.attr[4]) * 16

    @property
    def writeable(self):
        """Is True if new data can be written to the NDEF tag."""
        return bool(self.attr[10])

    @property
    def attr(self):
        if self._attr is None:
            self._attr = bytearray(self.tag.read(blocks=[0]))
            if not sum(self.attr[0:14]) == self.attr[14] << 8 | self.attr[15]:
                log.error("checksum error in ndef attribute block")
        return self._attr

    @property
    def message(self):
        """A 8-bit character string that contains the NDEF message data."""
        length = self.attr[11]*65536 + self.attr[12]*256 + self.attr[13]
        blocks = range(1, (length+15)/16 + 1)
        nb_max = self.attr[1] # Nbr
        data = ""
        while len(blocks) > nb_max:
            block_list = blocks[0:nb_max]
            data += self.tag.read(blocks[0:nb_max])
            del blocks[0:nb_max]
        if len(blocks) > 0:
            data += self.tag.read(blocks)
        self._attr = None
        return data[0:length]

    @message.setter
    def message(self, data):
        def split2(x): return [x/0x100, x%0x100]
        def split3(x): return [x/0x10000, x/0x100%0x100, x%0x100]

        if not self.writeable:
            raise IOError("tag writing disabled")

        if len(data) > self.capacity:
            raise IOError("ndef message beyond tag capacity")

        attr = self.attr
        attr[9] = 0x0F;
        attr[11:14] = split3(len(data))
        attr[14:16] = split2(sum(attr[0:14]))
        self.tag.write(attr, [0])

        blocks = range(1, (len(data)+15)/16 + 1)
        nb_max = attr[2] # blocks to write at once
        length = nb_max * 16  # bytes to write at once
        offset = 0
        while len(blocks) > nb_max:
            self.tag.write(data[offset:offset+length], blocks[0:nb_max])
            del blocks[0:nb_max]
            offset += length
        if len(blocks) > 0:
            data += (-len(data) % 16) * '\x00'
            self.tag.write(data[offset:], blocks)

        attr[9] = 0x00; # Writing finished
        attr[14:16] = split2(sum(attr[0:14]))
        self.tag.write(attr, [0])
        self._attr = None

class Type3Tag(tag.TAG):
    def __init__(self, clf, target):
        self.clf = clf
        self.idm = target["IDm"]
        self.pmm = target["PMm"]
        self.sys  = target["SYS"]
        rto, wto = self.pmm[5], self.pmm[6]
        self.rto = ((rto&0x07)+1, (rto>>3&0x07)+1, 0.302 * 4**(rto >> 6))
        self.wto = ((wto&0x07)+1, (wto>>3&0x07)+1, 0.302 * 4**(wto >> 6))
        self._ndef = None
        if self.sys == "\x12\xFC":
            try: self._ndef = NDEF(self)
            except Exception as e: log.error(str(e))

    def __str__(self):
        params = list()
        params.append(str(self.idm).encode("hex"))
        params.append(str(self.pmm).encode("hex"))
        params.append(str(self.sys).encode("hex"))
        return "Type3Tag IDm=%s PMm=%s SYS=%s" % tuple(params)

    @property
    def _is_present(self):
        """True if the tag is still within communication range."""
        rto = int((self.rto[0] + self.rto[1]) * self.rto[2]) + 5
        cmd = "\x04" + self.idm
        rsp = None
        if self.clf.dev.tt3_send_command(chr(len(cmd)+1) + cmd):
            rsp = self.clf.dev.tt3_recv_response(timeout=rto)
            if not rsp:
                cmd = "\x00" + self.sys + "\x00\x00"
                if self.clf.dev.tt3_send_command(chr(len(cmd)+1) + cmd):
                    rsp = self.clf.dev.tt3_recv_response(timeout=rto)
        return bool(rsp)

    def read(self, blocks, service=ndef_read_service):
        """Read service data blocks from tag. The *service* argument is the
        tag type 3 service code to use, 0x000b for reading NDEF. The *blocks*
        argument holds a list of integers representing the block numbers to
        read. The data is returned as a character string."""

        log.debug("read blocks " + repr(blocks))
        cmd  = "\x06" + self.idm # ReadWithoutEncryption
        cmd += "\x01" + ("%02X%02X" % (service%256,service/256)).decode("hex")
        cmd += chr(len(blocks))
        for block in blocks:
            if block < 256: cmd += "\x80" + chr(block)
            else: cmd += "\x00" + chr(block%256) + chr(block/256)
        rto = int((self.rto[0] + self.rto[1] * len(blocks)) * self.rto[2]) + 5
        log.debug("read timeout is {0} ms".format(rto))
        if not self.clf.dev.tt3_send_command(chr(len(cmd)+1) + cmd):
            raise IOError("tt3 send error")
        resp = self.clf.dev.tt3_recv_response(rto)
        if resp is None:
            raise IOError("tt3 recv error")
        if not resp.startswith(chr(len(resp)) + "\x07" + self.idm):
            raise IOError("tt3 data error")
        if resp[10] != 0 or resp[11] != 0:
            raise IOError("tt3 cmd error {0:02x} {1:02x}".format(*resp[10:12]))
        data = str(resp[13:])
        log.debug("<<< {0}".format(data.encode("hex")))
        return data

    def write(self, data, blocks, service=ndef_write_service):
        """Write service data blocks to tag. The *service* argument is the
        tag type 3 service code to use, 0x0009 for writing NDEF. The *blocks*
        argument holds a list of integers representing the block numbers to
        write. The *data* argument must be a character string with length
        equal to the number of blocks times 16."""

        log.debug("write blocks " + repr(blocks))
        if len(data) != len(blocks) * 16:
            log.error("data length does not match block-count * 16")
            raise ValueError("invalid data length for given number of blocks")
        log.debug(">>> {0}".format(str(data).encode("hex")))
        cmd  = "\x08" + self.idm # ReadWithoutEncryption
        cmd += "\x01" + ("%02X%02X" % (service%256,service/256)).decode("hex")
        cmd += chr(len(blocks))
        for block in blocks:
            if block < 256: cmd += "\x80" + chr(block)
            else: cmd += "\x00" + chr(block%256) + chr(block/256)
        cmd += data
        wto = int((self.wto[0] + self.wto[1] * len(blocks)) * self.wto[2]) + 5
        log.debug("write timeout is {0} ms".format(wto))
        if not self.clf.dev.tt3_send_command(chr(len(cmd)+1) + cmd):
            raise IOError("tt3 send error")
        resp = self.clf.dev.tt3_recv_response(timeout=wto)
        if resp is None:
            raise IOError("tt3 recv error")
        if not resp.startswith(chr(len(resp)) + "\x09" + self.idm):
            raise IOError("tt3 data error")
        if resp[10] != 0 or resp[11] != 0:
            raise IOError("tt3 cmd error {0:02x} {1:02x}".format(*resp[10:12]))

class Type3TagEmulation(object):
    def __init__(self, idm, pmm, system_code="\x12\xFC", baud_rate="424"):
        self.clf = None
        self.idm = bytearray(idm)
        self.pmm = bytearray(pmm)
        self.sc = bytearray(system_code)
        self.br = baud_rate
        self.services = dict()

    def __str__(self):
        return "Type3TagEmulation IDm={0} PMm={1} SC={2} BR={3}".format(
            str(self.idm).encode("hex"), str(self.pmm).encode("hex"),
            str(self.sc).encode("hex"), self.br)

    def add_service(self, service_code, block_read_func, block_write_func):
        self.services[service_code] = (block_read_func, block_write_func)

    def wait_command(self, timeout):
        """Wait *timeout* ms for a reader command."""
        if self.cmd is None:
            self.cmd = self.clf.dev.tt3_wait_command(timeout)
            if self.cmd and len(self.cmd) != self.cmd[0]:
                log.error("tt3 command length error")
                self.cmd = None
        return self.cmd

    def send_response(self):
        rsp = None
        log.debug("tt3: processing command " + str(self.cmd).encode("hex"))
        if tuple(self.cmd[0:4]) in [(6, 0, 255, 255), (6, 0) + tuple(self.sc)]:
            rsp = self.polling(self.cmd[2:])
            rsp = bytearray([2 + len(rsp), 0x01]) + rsp
        if self.cmd[1] == 0x04 and self.cmd[2:10] == self.idm:
            rsp = self.request_response(self.cmd[10:])
            rsp = bytearray([10 + len(rsp), 0x05]) + self.idm + rsp
        elif self.cmd[1] == 0x06 and self.cmd[2:10] == self.idm:
            rsp = self.read_without_encryption(self.cmd[10:])
            rsp = bytearray([10 + len(rsp), 0x07]) + self.idm + rsp
        elif self.cmd[1] == 0x08 and self.cmd[2:10] == self.idm:
            rsp = self.write_without_encryption(self.cmd[10:])
            rsp = bytearray([10 + len(rsp), 0x09]) + self.idm + rsp
        elif self.cmd[1] == 0x0C and self.cmd[2:10] == self.idm:
            rsp = self.request_system_code(self.cmd[10:])
            rsp = bytearray([10 + len(rsp), 0x0D]) + self.idm + rsp
        if rsp is not None:
            log.debug("tt3: sending response " + str(rsp).encode("hex"))
            self.clf.dev.tt3_send_response(rsp)
        self.cmd = None

    def polling(self, cmd_data):
        if cmd_data[2] == 1:
            rsp = self.idm + self.pmm + self.sc
        else:
            rsp = self.idm + self.pmm
        return rsp
    
    def request_response(self, cmd_data):
        return bytearray([0])
    
    def read_without_encryption(self, cmd_data):
        service_list = cmd_data.pop(0) * [[None, None]]
        for i in range(len(service_list)):
            service_code = cmd_data[1] << 8 | cmd_data[0]
            if not service_code in self.services.keys():
                return bytearray([255, 0xA1])
            service_list[i] = [service_code, 0]
            del cmd_data[0:2]
        
        service_block_list = cmd_data.pop(0) * [None]
        for i in range(len(service_block_list)):
            try:
                service_list_item = service_list[cmd_data[0] & 0x0F]
                service_code = service_list_item[0]
                service_list_item[1] += 1
            except IndexError:
                return bytearray([1<<(i%8), 0xA3])
            if cmd_data[0] >= 128:
                block_number = cmd_data[1]
                del cmd_data[0:2]
            else:
                block_number = cmd_data[2] << 8 | cmd_data[1]
                del cmd_data[0:3]
            service_block_list[i] = [service_code, block_number, 0]

        service_block_count = dict(service_list)
        for service_block_list_item in service_block_list:
            service_code = service_block_list_item[0]
            service_block_list_item[2] = service_block_count[service_code]
            
        block_data = bytearray()
        for i, service_block_list_item in enumerate(service_block_list):
            service_code, block_number, block_count = service_block_list_item
            # rb (read begin) and re (read end) mark an atomic read
            rb = bool(block_count == service_block_count[service_code])
            service_block_count[service_code] -= 1
            re = bool(service_block_count[service_code] == 0)
            read_func, write_func = self.services[service_code]
            one_block_data = read_func(block_number, rb, re)
            if one_block_data is None:
                return bytearray([1<<(i%8), 0xA2, 0])
            block_data.extend(one_block_data)
            
        return bytearray([0, 0, len(block_data)/16]) + block_data

    def write_without_encryption(self, cmd_data):
        service_list = cmd_data.pop(0) * [[None, None]]
        for i in range(len(service_list)):
            service_code = cmd_data[1] << 8 | cmd_data[0]
            if not service_code in self.services.keys():
                return bytearray([255, 0xA1])
            service_list[i] = [service_code, 0]
            del cmd_data[0:2]
            
        service_block_list = cmd_data.pop(0) * [None]
        for i in range(len(service_block_list)):
            try:
                service_list_item = service_list[cmd_data[0] & 0x0F]
                service_code = service_list_item[0]
                service_list_item[1] += 1
            except IndexError:
                return bytearray([1<<(i%8), 0xA3])
            if cmd_data[0] >= 128:
                block_number = cmd_data[1]
                del cmd_data[0:2]
            else:
                block_number = cmd_data[2] << 8 | cmd_data[1]
                del cmd_data[0:3]
            service_block_list[i] = [service_code, block_number, 0]

        service_block_count = dict(service_list)
        for service_block_list_item in service_block_list:
            service_code = service_block_list_item[0]
            service_block_list_item[2] = service_block_count[service_code]
            
        block_data = cmd_data[0:]
        if len(block_data) % 16 != 0:
            return bytearray([255, 0xA2])
            
        for i, service_block_list_item in enumerate(service_block_list):
            service_code, block_number, block_count = service_block_list_item
            # wb (write begin) and we (write end) mark an atomic write
            wb = bool(block_count == service_block_count[service_code])
            service_block_count[service_code] -= 1
            we = bool(service_block_count[service_code] == 0)
            read_func, write_func = self.services[service_code]
            if not write_func(block_number, block_data[i*16:(i+1)*16], wb, we):
                return bytearray([1<<(i%8), 0xA2, 0])

        return bytearray([0, 0])

    @trace
    def request_system_code(self, cmd_data):
        return '\x01' + self.sc
