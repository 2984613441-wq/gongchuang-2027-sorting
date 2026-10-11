"""Capture commands, timestamps, raw merged output and exit codes in UTF-8."""
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT / '电控/src'))
jobs = {
    'probe': ('chain-probe-output.txt', ['py', '-3', str(HERE / 'chain_probe.py')], ROOT),
    'tests': ('related-tests-output.txt', ['py', '-3', '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                'tests/rpi/test_vision_ingest.py', 'tests/rpi/test_socket_vision_source.py',
                'tests/rpi/test_pixel_to_device.py', 'tests/rpi/test_two_stage_display.py',
                'tests/protocol/test_item_task_identity.py', 'tests/rpi/test_display.py'], ROOT / '电控'),
    'bridge': ('bridge-selftest-output.txt', ['py', '-3', '视觉/src/maixcam_deploy/v6_bridge.py'], ROOT),
}
test_tmp = (HERE / ('pytest-tmp-' + uuid.uuid4().hex)).resolve()
assert test_tmp.is_relative_to(HERE.resolve()) and not test_tmp.exists()
jobs['tests-workspace'] = ('related-tests-workspace-output.txt',
                          jobs['tests'][1] + ['--basetemp', str(test_tmp), '--tb=short', '-rs'],
                          jobs['tests'][2])
jobs['tests-verified'] = ('related-tests-verified-output.txt', jobs['tests-workspace'][1], jobs['tests'][2])
sys.stdout.reconfigure(encoding='utf-8')
for key in sys.argv[1:] or ['probe']:
    filename, args, cwd = jobs[key]
    before = datetime.now().astimezone().isoformat()
    result = subprocess.run(args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding='utf-8', errors='replace', timeout=180)
    text = (f'started={before}\ncwd={cwd}\ncommand={subprocess.list2cmdline(args)}\n'
            f'PYTHONPATH={env["PYTHONPATH"]}\nPYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1\n'
            '--- RAW OUTPUT ---\n' + result.stdout + f'\n--- END RAW OUTPUT ---\nexit_code={result.returncode}\n'
            f'finished={datetime.now().astimezone().isoformat()}\n')
    (HERE / filename).write_text(text, encoding='utf-8')
    print(text)
    if result.returncode:
        sys.exit(result.returncode)
