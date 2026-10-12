"""Strict RECORD and ARM64 PE audit; independent of native execution."""
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import zipfile


def audit_bytes(payload):
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            raise ValueError('RECORD duplicate ZIP members')
        records = [n for n in names if n.endswith('.dist-info/RECORD')]
        if len(records) != 1: raise ValueError('RECORD must be unique')
        rows = list(csv.reader(io.StringIO(z.read(records[0]).decode())))
        if len(rows) != len({row[0] for row in rows}): raise ValueError('RECORD duplicate rows')
        if {r[0] for r in rows} != {n for n in names if not n.endswith('/')}:
            raise ValueError('RECORD coverage mismatch')
        for n,digest,size in rows:
            b=z.read(n)
            if n == records[0]: continue
            if not digest or not size: raise ValueError('RECORD missing hash or size: '+n)
            algo,wanted=digest.split('=',1)
            actual=base64.urlsafe_b64encode(hashlib.new(algo,b).digest()).rstrip(b'=').decode()
            if actual != wanted or len(b) != int(size): raise ValueError('RECORD hash/size: '+n)
        binaries=[]
        for n in names:
            if n.lower().endswith(('.pyd','.dll','.exe')):
                b=z.read(n)
                if b[:2] != b'MZ': raise ValueError('invalid PE: '+n)
                off=struct.unpack_from('<I',b,60)[0]
                if b[off:off+4] != b'PE\0\0': raise ValueError('invalid PE signature: '+n)
                machine=struct.unpack_from('<H',b,off+4)[0]
                binaries.append({'name':n,'machine':hex(machine),'sha256':hashlib.sha256(b).hexdigest()})
                if machine != 0xAA64: raise ValueError('architecture not native ARM64: '+n+' '+hex(machine))
        if not binaries: raise ValueError('native wheel contains no PE payloads')
        return {'sha256':hashlib.sha256(payload).hexdigest(),'record_members':len(rows),'binaries':binaries}

if __name__ == '__main__':
    result={str(p):audit_bytes(p.read_bytes()) for p in Path(sys.argv[1]).glob('*.whl')}
    if not result: raise RuntimeError('No wheels to audit')
    Path(sys.argv[2]).write_text(json.dumps(result,indent=2))
    print(json.dumps({k:len(v['binaries']) for k,v in result.items()}))
