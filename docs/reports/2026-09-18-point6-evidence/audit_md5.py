"""Read-only Pi audit over SSH stdin: no upload/import of project/hardware access.

Run from repository root: py -3 docs/reports/2026-09-18-point6-evidence/audit_md5.py
The remote worker only reads regular project files, hashes them and lists backup
directory names. MD5 is a byte-comparison checksum, not a security signature.
"""
import csv
import datetime
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from collections import Counter

ROOT = Path(__file__).resolve().parents[3] if __file__ != '<stdin>' else None
OUT = Path(__file__).resolve().parent if ROOT else None
TREES = ['电控/deploy', '电控/src/electrical_control']
EXTRA = ['电控/calibration_config.ini', '工具/pi_sync_pkg.sh',
         '工具/pi_fix_deploy.sh', '工具/pi_start_chain.sh']
TEXTS = ['sorting_config.ini', '电控/deploy/sorting_config.ini',
         '电控/deploy/names.json', '电控/calibration_config.ini',
         '工具/pi_sync_pkg.sh', '工具/pi_fix_deploy.sh', '工具/pi_start_chain.sh',
         'pi_sync_pkg.sh', 'pi_fix_deploy.sh', 'pi_start_chain.sh']


def manifest(base):
    files, errors = {}, []
    def one(p):
        key = p.relative_to(base).as_posix()
        try:
            if p.is_symlink():
                files[key] = {'kind': 'symlink', 'target': os.readlink(str(p))}
                return
            st = p.stat()
            data = p.read_bytes()
            end = p.stat()
            files[key] = dict(kind='file', size=len(data), md5=hashlib.md5(data).hexdigest(),
                              mtime_ns=st.st_mtime_ns,
                              stable=(st.st_size, st.st_mtime_ns) == (end.st_size, end.st_mtime_ns))
        except OSError as e:
            errors.append({'path': key, 'error': str(e)})
    for tree in TREES:
        p = base / tree
        if not p.is_dir():
            errors.append({'path': tree, 'error': 'root missing'})
            continue
        for d, dirs, names in os.walk(str(p), followlinks=False,
                                     onerror=lambda e: errors.append({'error': str(e)})):
            for name in sorted(dirs):
                q = Path(d) / name
                if q.is_symlink():
                    one(q)
            for name in sorted(names):
                one(Path(d) / name)
    for name in EXTRA:
        p = base / name
        if p.exists() or p.is_symlink():
            one(p)
    return dict(host=socket.gethostname(), python=sys.version, root=str(base),
                utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                files=files, errors=errors)


def remote():
    base = Path('/home/pi')
    result = manifest(base)
    result['texts'] = {}
    for name in TEXTS:
        try:
            result['texts'][name] = (base / name).read_text(encoding='utf-8')
        except OSError as e:
            result['texts'][name] = {'error': str(e)}
    result['historical_directories'] = []
    for pattern in ('_stage', '电控_*.quarantine-*'):
        for p in sorted(base.glob(pattern)):
            result['historical_directories'].append(str(p))
    result['images'] = [str(p) for p in sorted((base / 'images').glob('*'))]
    result['errors'].extend([])
    print(json.dumps(result, ensure_ascii=True))


def main():
    local = manifest(ROOT)
    (OUT / 'local-md5-before.json').write_text(json.dumps(local, ensure_ascii=False, indent=2), encoding='utf-8')
    target = sys.argv[sys.argv.index('--ssh') + 1] if '--ssh' in sys.argv else 'pi@172.20.10.8'
    command = [r'C:\Windows\System32\OpenSSH\ssh.exe', '-o', 'BatchMode=yes',
               '-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'UpdateHostKeys=no', target, 'python3', '-B', '-', '--remote']
    (OUT / 'ssh-command.json').write_text(json.dumps(command, indent=2), encoding='utf-8')
    try:
        p = subprocess.run(command, input=Path(__file__).read_bytes(), capture_output=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired) as e:
        (OUT / 'ssh-error.txt').write_text(str(e), encoding='utf-8')
        print(str(e))
        return 3
    (OUT / 'ssh-stderr.txt').write_bytes(p.stderr)
    (OUT / 'remote-stdout.json').write_bytes(p.stdout)
    print('SSH exit:', p.returncode)
    if p.returncode:
        print(p.stderr.decode('utf-8', 'replace'))
        with (OUT / 'local-md5-remote-unavailable.csv').open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f)
            w.writerow(['path', 'category', 'local_md5', 'size', 'remote_md5', 'status'])
            for path, meta in sorted(local['files'].items()):
                w.writerow([path, 'cache' if '__pycache__' in path.split('/') else 'project',
                            meta.get('md5', ''), meta.get('size', ''), '', 'REMOTE_UNAVAILABLE'])
        return p.returncode
    other = json.loads(p.stdout)
    local_after = manifest(ROOT)
    (OUT / 'local-md5-after.json').write_text(json.dumps(local_after, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = []
    for key in sorted(set(local['files']) | set(other['files'])):
        l, r = local['files'].get(key), other['files'].get(key)
        if l is None:
            status = 'REMOTE_ONLY'
        elif r is None:
            status = 'LOCAL_ONLY'
        elif l['kind'] != 'file' or r['kind'] != 'file':
            status = 'SYMLINK_REVIEW'
        elif not l.get('stable') or not r.get('stable') or l != local_after['files'].get(key):
            status = 'CHANGED_DURING_AUDIT'
        else:
            status = 'SAME' if l['md5'] == r['md5'] else 'DIFF'
        rows.append(dict(path=key, category='cache' if '__pycache__' in key.split('/') else 'project',
                         status=status, local_md5=(l or {}).get('md5', ''),
                         remote_md5=(r or {}).get('md5', ''),
                         local_size=(l or {}).get('size', ''), remote_size=(r or {}).get('size', '')))
    with (OUT / 'md5-comparison.csv').open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summary = dict(local_utc=local['utc'], remote_utc=other['utc'],
                   project_counts=dict(Counter(r['status'] for r in rows if r['category'] == 'project')),
                   cache_counts=dict(Counter(r['status'] for r in rows if r['category'] == 'cache')),
                   local_errors=local['errors'], remote_errors=other['errors'])
    (OUT / 'md5-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    for r in rows:
        if r['category'] == 'project' and (r['status'] != 'SAME' or r['path'].endswith('run_chain.py')):
            print(json.dumps(r, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    if '--remote' in sys.argv:
        remote()
    else:
        raise SystemExit(main())
