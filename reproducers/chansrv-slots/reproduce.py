"""Run the channel-slot regression on temporary copies of a pinned XRDP source."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

BASE = '62987220b8550d5fef750ba5678c5ea987d92902'
SOURCE = 'sesman/chansrv/chansrv.c'

def run(args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, timeout=60, check=False)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def main():
    if len(sys.argv) != 3:
        raise SystemExit('Usage: python3 reproduce.py /path/to/xrdp /path/to/reference.patch')
    repo, patch = (Path(value).resolve() for value in sys.argv[1:])
    probe = Path(__file__).with_name('check-slots.py')
    original = run(['git', '-C', str(repo), 'show', f'{BASE}:{SOURCE}'])
    if original.returncode:
        raise SystemExit(original.stderr.decode())
    result = {'baseCommit': BASE, 'patchSHA256': digest(patch.read_bytes()),
              'probeSHA256': digest(probe.read_bytes()), 'scope': 'Source-level allocator/disconnect test; simulated transport, no server session',
              'compiler': run(['cc', '--version']).stdout.decode().splitlines()[0], 'runs': {}}
    with tempfile.TemporaryDirectory(prefix='xrdp-slot-repro-') as directory:
        root = Path(directory)
        for variant in ('original', 'patched'):
            tree = root / variant
            source = tree / SOURCE
            source.parent.mkdir(parents=True)
            source.write_bytes(original.stdout)
            if variant == 'patched':
                applied = run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch)], cwd=tree)
                if applied.returncode:
                    raise SystemExit(applied.stderr.decode() + applied.stdout.decode())
            args = [sys.executable, str(probe), str(source)]
            if variant == 'patched':
                args.append('--expect-fixed')
            test = run(args)
            rows = [json.loads(line) for line in test.stdout.decode().splitlines() if line.startswith('{')]
            observed = (rows == [{'failed_cycle': 128, 'occupied_slots': 255, 'unassigned_id': 0}] if variant == 'original' else
                        rows == [{'completed_cycles': 1000, 'static_clients_preserved': 1, 'dynamic_clients_closed': 2000},
                                 {'allocated_dechunkers': 2000, 'freed_dechunkers': 2000}])
            result['runs'][variant] = {'sourceSHA256': digest(source.read_bytes()), 'exitCode': test.returncode,
                                       'observations': rows, 'expectedResultObserved': observed and test.returncode == 0,
                                       'compilerDiagnostics': test.stderr.decode()}
    print(json.dumps(result, indent=2))
    return 0 if all(row['expectedResultObserved'] for row in result['runs'].values()) else 1

if __name__ == '__main__':
    raise SystemExit(main())
