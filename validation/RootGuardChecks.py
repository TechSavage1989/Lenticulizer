from pathlib import Path
import shutil, subprocess, sys, tempfile
root=Path(__file__).resolve().parents[1]
check=root/'scripts/check_root.py'
clean=subprocess.run([sys.executable,str(check)],cwd=root,capture_output=True,text=True)
assert clean.returncode==0, clean.stdout+clean.stderr
with tempfile.TemporaryDirectory() as td:
    clone=Path(td)/'source'
    shutil.copytree(root,clone,ignore=shutil.ignore_patterns('bin','obj','dist','.git'))
    (clone/'UNAPPROVED_ROOT_FILE.tmp').write_text('negative control',encoding='utf-8')
    bad=subprocess.run([sys.executable,str(clone/'scripts/check_root.py'),'--root',str(clone)],cwd=clone,capture_output=True,text=True)
    assert bad.returncode!=0, 'negative control unexpectedly passed'
    assert 'UNAPPROVED_ROOT_FILE.tmp' in bad.stdout, bad.stdout
print('PASS: root guard clean tree and isolated clutter negative control.')
