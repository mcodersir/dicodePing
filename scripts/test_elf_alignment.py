import struct,unittest
from verify_elf_alignment import verify_elf
class AlignmentTest(unittest.TestCase):
    def fixture(self,align,offset,address):
        blob=bytearray(120);blob[:6]=b'\x7fELF\x02\x01'
        struct.pack_into('<Q',blob,32,64);struct.pack_into('<HH',blob,54,56,1)
        struct.pack_into('<IIQQQQQQ',blob,64,1,5,offset,address,address,64,64,align)
        return bytes(blob)
    def test_rejects_old_4k_and_misaligned_load_segment(self):
        for b in [self.fixture(4096,4096,8192),self.fixture(16384,4096,8192)]:
            with self.assertRaises(ValueError):verify_elf(b,'arm64-v8a')
    def test_accepts_16k_congruent_segments(self):
        verify_elf(self.fixture(16384,2048,18432),'arm64-v8a')
if __name__=='__main__':unittest.main()
