import base64
import csv
import hashlib
import io
import struct
import unittest
import zipfile

from wheel_audit import audit_bytes


def fixture(machine=0xAA64, corrupt=False):
    # Synthetic PE is a verifier unit fixture, never runtime evidence.
    pe = bytearray(160); pe[:2] = b'MZ'; struct.pack_into('<I', pe, 60, 80)
    pe[80:84] = b'PE\0\0'; struct.pack_into('<H', pe, 84, machine)
    members = {'sample/a.pyd': bytes(pe), 'sample-1.dist-info/METADATA': b'Name: sample\nVersion: 1\n'}
    rows = [(n, 'sha256='+base64.urlsafe_b64encode(hashlib.sha256(v).digest()).rstrip(b'=').decode(), str(len(v))) for n,v in members.items()]
    rows.append(('sample-1.dist-info/RECORD','',''))
    s=io.StringIO(); csv.writer(s).writerows(rows)
    members['sample-1.dist-info/RECORD']=s.getvalue().encode()
    if corrupt: members['sample/a.pyd'] += b'corrupt'
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        for n,v in members.items(): z.writestr(n,v)
    return out.getvalue()


class IntegrityTests(unittest.TestCase):
    def test_native_fixture(self):
        self.assertEqual(audit_bytes(fixture())['binaries'][0]['machine'], '0xaa64')
    def test_record_negative(self):
        with self.assertRaisesRegex(ValueError, 'RECORD'):
            audit_bytes(fixture(corrupt=True))
    def test_arch_negative_with_valid_record(self):
        with self.assertRaisesRegex(ValueError, 'architecture'):
            audit_bytes(fixture(machine=0x8664))

if __name__=='__main__': unittest.main()
