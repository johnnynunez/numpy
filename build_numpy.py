import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from wheel_audit import audit_bytes

p=argparse.ArgumentParser(); p.add_argument('--version',required=True); p.add_argument('--out',required=True); a=p.parse_args()
out=Path(a.out).resolve(); out.mkdir(parents=True,exist_ok=True)
spec=json.loads(Path(__file__).with_name('sources.json').read_text())
for key in [a.version,'openblas']:
    f=spec[key]; raw=urllib.request.urlopen(f['url'],timeout=90).read()
    assert hashlib.sha256(raw).hexdigest()==f['digests']['sha256']
    (out/f['filename']).write_bytes(raw)
(out/'source-provenance.json').write_text(json.dumps({key:spec[key] for key in [a.version,'openblas']},indent=2))
blaswheel=out/spec['openblas']['filename']
(out/'blas-integrity.json').write_text(json.dumps(audit_bytes(blaswheel.read_bytes()),indent=2))
subprocess.run([sys.executable,'-m','pip','install',str(blaswheel)],check=True)
subprocess.run([sys.executable,str(Path(__file__).with_name('preflight.py')),str(out)],check=True)
with tarfile.open(out/spec[a.version]['filename']) as t: t.extractall(out/'source',filter='data')
source=out/'source'/('numpy-'+a.version)
# Explicit old-release backport, not an unchanged 1.26.4 wheel.
assert a.version == '1.26.4'
fpu=source/'numpy/core/src/multiarray/_multiarray_tests.c.src'
original=fpu.read_text()
old='#elif (defined(__GNUC__) && (defined(__x86_64__) || defined(__i386__))) || (defined(_MSC_VER) && defined(__clang__))'
new='#elif (defined(__GNUC__) && (defined(__x86_64__) || defined(__i386__))) || (defined(_MSC_VER) && defined(__clang__) && (defined(_M_IX86) || defined(_M_AMD64)))'
assert original.count(old)==1
fpu.write_text(original.replace(old,new))
version=a.version+'+winarm64.1'
project=source/'pyproject.toml'; text=project.read_text(); assert text.count('version = "'+a.version+'"')==1
project.write_text(text.replace('version = "'+a.version+'"','version = "'+version+'"'))
# Runtime version is generated from the release version module.
versionfile=source/'numpy/version.py'; text=versionfile.read_text()
assert a.version in text
versionfile.write_text(text.replace(a.version,version))
(out/'backport.json').write_text(json.dumps({'base_version':a.version,'version':version,'upstream_commits':['a75a389d0e6b0fe3f983946be986d6ea2864d23a','05be6f63f9573ea66ac92a93856593da451a8fd6'],'source_path':str(fpu),'old_guard':old,'new_guard':new,'parent_constraints_changed':False},indent=2))
import scipy_openblas32 as blas
pc=out/'pkgconfig'; pc.mkdir(exist_ok=True)
(pc/'scipy-openblas.pc').write_text(blas.get_pkg_config())
os.environ['PKG_CONFIG_PATH']=str(pc)
# Upstream prescribed loader artifact; no numerical source or dependency pin edit.
(source/'numpy/_distributor_init_local.py').write_text('# DLL loading is inserted by delvewheel during repair.\n')
(out/'packaging-overlay.json').write_text(json.dumps({'path':'numpy/_distributor_init_local.py','content':'# DLL loading is inserted by delvewheel during repair.\n','source_modified_elsewhere':True,'blas_integer_abi':'LP64','no_blas_fallback':False},indent=2))
rawdir=out/'raw-wheel'; rawdir.mkdir(exist_ok=True)
cmd=[sys.executable,'-m','build','--wheel','--no-isolation','--outdir',str(rawdir),str(source),'-Csetup-args=-Dblas=openblas','-Csetup-args=-Dlapack=openblas','-Csetup-args=-Dallow-noblas=false','-Csetup-args=-Duse-ilp64=false','-Ccompile-args=-j2']
(out/'build-command.json').write_text(json.dumps(cmd,indent=2))
with (out/'build.log').open('w') as log:
    r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
print('build exit',r.returncode,flush=True)
(out/'build-result.json').write_text(json.dumps({'returncode':r.returncode}))
if r.returncode: raise SystemExit(r.returncode)
whl=next(rawdir.glob('*.whl')); repaired=out/'wheels'
subprocess.run([sys.executable,'-m','delvewheel','repair',str(whl),'--add-path',blas.get_lib_dir(),'-w',str(repaired)],check=True)
wheel=next(repaired.glob('*.whl'))
(out/'wheel-integrity.json').write_text(json.dumps(audit_bytes(wheel.read_bytes()),indent=2))
# Test in a second clean venv without scipy_openblas32 installed.
venv=out/'test-venv'; subprocess.run([sys.executable,'-m','venv',str(venv)],check=True); py=str(venv/'Scripts/python.exe')
subprocess.run([py,'-m','pip','install',str(wheel),'pytest==8.4.2','pytest-timeout==2.4.0','hypothesis==6.169.0','threadpoolctl==3.7.0'],check=True)
subprocess.run([py,'-c','import numpy as n; assert n.__version__=="'+version+'"; n.testing.assert_allclose(n.linalg.solve([[3.,1.],[1.,2.]],[9.,8.]),[2.,3.]); n.show_config()'],cwd=out,check=True)
with (out/'full-numpy.log').open('w') as log:
    r=subprocess.run([py,'-m','pytest','--pyargs','numpy','-q','--timeout=90','--junitxml='+str(out/'full-numpy.xml')],cwd=out,stdout=log,stderr=subprocess.STDOUT)
raise SystemExit(r.returncode)
