#!/usr/bin/env python3
from pathlib import Path
import argparse, subprocess, sys

ROOT = Path(__file__).resolve().parents[1]
ALLOW = {line.strip() for line in (ROOT/'scripts/root-allowlist.txt').read_text(encoding='utf-8').splitlines() if line.strip() and not line.lstrip().startswith('#')}
GENERATED = {'bin','obj','dist','.vs','.idea','.vscode'}

def root_names(root: Path):
    git = root/'.git'
    if git.exists():
        try:
            out=subprocess.check_output(['git','-C',str(root),'ls-files','-z'],stderr=subprocess.DEVNULL)
            names={Path(p.decode('utf-8')).parts[0] for p in out.split(b'\0') if p}
            return {n for n in names if n not in GENERATED}
        except Exception:
            pass
    return {p.name for p in root.iterdir() if p.name not in GENERATED and p.name != '.git'}

def check(root: Path):
    actual=root_names(root)
    unexpected=sorted(actual-ALLOW)
    missing=sorted({'README.md','AGENTS.md','DEVELOPMENT_HANDOFF.md','Lenticulizer.csproj'}-actual)
    return unexpected,missing

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=ROOT)
    args=parser.parse_args()
    unexpected,missing=check(args.root.resolve())
    if unexpected:
        print('FAIL: unexpected tracked/source-root entries: '+', '.join(unexpected))
    if missing:
        print('FAIL: required root entries missing: '+', '.join(missing))
    if unexpected or missing: return 1
    print('PASS: source root matches scripts/root-allowlist.txt')
    return 0
if __name__=='__main__': raise SystemExit(main())
