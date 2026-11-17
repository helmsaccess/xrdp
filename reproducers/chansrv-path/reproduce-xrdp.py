#!/usr/bin/env python3
"""Run the real parser against libc and the project's own string-copy fallback."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

PARSER_SHA = '975ff03df3b308cf7e903f24dc246a5e4dbd3aa769313264fac25c2d335587b5'
STRINGS_SHA = '1b3a86604bf34fb7c15e895a159a41697d13a094fcacd398719a860dad1e86c8'
PATCH_SHA = '80b198f5d2837d59674244314cabad5e9a80e6fd514cedaee7f7eb56c2ec77ce'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkout', type=Path)
    parser.add_argument('patch', type=Path)
    args = parser.parse_args()
    assert sha(args.checkout/'xrdp/xrdp_mm.c') == PARSER_SHA
    assert sha(args.checkout/'common/string_calls.c') == STRINGS_SHA
    assert sha(args.patch) == PATCH_SHA
    checker = Path(__file__).with_name('check-parser.py')
    report = {'sourceCommit': '62987220b8550d5fef750ba5678c5ea987d92902',
              'patchSha256': PATCH_SHA, 'checkerSha256': sha(checker),
              'compiler': subprocess.check_output(['cc','--version'],text=True).splitlines()[0],
              'libc': subprocess.check_output(['getconf','GNU_LIBC_VERSION'],text=True).strip(),
              'stringHeaderSha256': sha(Path('/usr/include/string.h')), 'variants': {}}
    with tempfile.TemporaryDirectory(prefix='xrdp-parser-pair-') as name:
        root=Path(name)
        for phase in ('original','patched'):
            tree=root/phase
            for relative in ('xrdp/xrdp_mm.c','common/string_calls.c'):
                target=tree/relative;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(args.checkout/relative,target)
            if phase=='patched':
                subprocess.run(['patch','--batch','--fuzz=0','-p1','-i',str(args.patch.resolve())],cwd=tree,check=True,capture_output=True,timeout=10)
            run=subprocess.run(['python3',str(checker),str(tree/'xrdp/xrdp_mm.c')],capture_output=True,text=True,timeout=120)
            report['variants'][phase]=json.loads(run.stdout)
    original=report['variants']['original'];patched=report['variants']['patched']
    assert original['allChecksAvailable'] and patched['allChecksAvailable']
    before={item['binding']:item['exitCode'] for item in original['results']}
    assert before['libc-plain']==0 and before['actual-xrdp-fallback']==0
    assert before['libc-nonnull-sanitizer-trap'] != 0
    assert patched['passed']
    report['expectedRedGreenConfirmed']=True
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    main()
