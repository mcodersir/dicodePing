"""Reject native 64-bit ELF segments that cannot be loaded on 16 KB Android."""
import struct

def verify_elf(data: bytes, abi: str, label: str = ''):
    if data[:4] != b'\x7fELF': raise ValueError('Not ELF: '+label)
    if abi not in ('arm64-v8a','x86_64'): return
    if data[4:6] != b'\x02\x01': raise ValueError('Wrong ELF class/endianness: '+label)
    offset = struct.unpack_from('<Q',data,32)[0]
    size,count = struct.unpack_from('<HH',data,54)
    loads = 0
    for i in range(count):
        kind,flags,file_offset,address,physical,file_size,memory_size,alignment = struct.unpack_from('<IIQQQQQQ',data,offset+i*size)
        if kind == 1:
            loads += 1
            if alignment < 16384 or file_offset % 16384 != address % 16384:
                raise ValueError('Native segment is not 16 KB compatible: '+label)
    if not loads: raise ValueError('ELF has no loadable segments: '+label)
