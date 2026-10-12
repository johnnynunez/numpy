"""Native LP64 provider and public compiler preflight; no SciPy claim."""
import ctypes as c
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import pefile
import scipy_openblas32 as blas

out=Path(sys.argv[1]); out.mkdir(exist_ok=True,parents=True)
assert sysconfig.get_platform()=='win-arm64'
libpath=Path(blas.get_lib_dir())/'scipy_openblas.dll'
pe=pefile.PE(str(libpath))
exports={x.name.decode() for x in pe.DIRECTORY_ENTRY_EXPORT.symbols if x.name}
assert pe.FILE_HEADER.Machine==0xaa64
config=blas.get_openblas_config()
assert 'USE64BITINT' not in config
lib=c.CDLL(str(libpath))
# Fortran LP64 DGESV API, column-major known solution [2, 3].
f=lib.scipy_dgesv_
f.argtypes=[c.POINTER(c.c_int),c.POINTER(c.c_int),c.POINTER(c.c_double),c.POINTER(c.c_int),c.POINTER(c.c_int),c.POINTER(c.c_double),c.POINTER(c.c_int),c.POINTER(c.c_int)]
n=c.c_int(2); nr=c.c_int(1); ld=c.c_int(2); info=c.c_int(-99)
a=(c.c_double*4)(3,1,1,2); b=(c.c_double*2)(9,8); piv=(c.c_int*2)()
f(c.byref(n),c.byref(nr),a,c.byref(ld),piv,b,c.byref(ld),c.byref(info))
assert info.value==0 and abs(b[0]-2)<1e-12 and abs(b[1]-3)<1e-12
report={'platform':sysconfig.get_platform(),'openblas_config':config,'dll':str(libpath),'machine':hex(pe.FILE_HEADER.Machine),'fortran_dgesv_lp64':list(b),'legacy_symbols':{x:x in exports for x in ['dgemm_','dgesv_','scipy_dgemm_','scipy_dgesv_']},'imports':[x.dll.decode() for x in pe.DIRECTORY_ENTRY_IMPORT], 'compilers':{},'limits':'BLAS DLL call proves LP64 DGESV only; not full old SciPy Fortran or complex ABI, threading or f2py.'}
for name in ['cl','clang-cl','flang','flang-new','link','dumpbin']:
    path=shutil.which(name)
    if path:
        r=subprocess.run([path,'--version'] if name not in ['cl','link','dumpbin'] else [path],capture_output=True)
        report['compilers'][name]={'path':path,'version_output':(r.stdout+r.stderr).decode(errors='replace'),'returncode':r.returncode}
    else: report['compilers'][name]={'path':None}
# Exercise the installed Fortran compiler and native CRT link if present.
fc=shutil.which('flang') or shutil.which('flang-new')
if fc:
    source=out/'fortran_probe.f90'
    source.write_text('program test\nuse iso_c_binding\nimplicit none\nreal(c_double) :: x\nx = sqrt(4.0_c_double)\nif (abs(x-2.0_c_double)>1.0e-12_c_double) stop 1\nprint *, "FORTRAN_NATIVE_OK", x\nend program test\n')
    exe=out/'fortran_probe.exe'
    r=subprocess.run([fc,str(source),'-o',str(exe)],capture_output=True)
    report['fortran_compile']={'returncode':r.returncode,'stdout':r.stdout.decode(errors='replace'),'stderr':r.stderr.decode(errors='replace')}
    if r.returncode==0:
        machine=pefile.PE(str(exe)).FILE_HEADER.Machine
        assert machine==0xaa64
        r=subprocess.run([str(exe)],capture_output=True)
        report['fortran_run']={'returncode':r.returncode,'stdout':r.stdout.decode(errors='replace'),'stderr':r.stderr.decode(errors='replace'),'machine':hex(machine)}
(out/'preflight.json').write_text(json.dumps(report,indent=2)); print(json.dumps(report,indent=2))
