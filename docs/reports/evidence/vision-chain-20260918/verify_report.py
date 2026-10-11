"""Verify local report citation ranges and save the cited-file hashes."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
REPORT = ROOT / 'docs/reports/视觉链路核对-2026-09-18.md'
aliases = {
    'M': '视觉/src/maixcam_deploy/main.py', 'C': '视觉/src/maixcam_deploy/capture.py',
    'V': '视觉/src/maixcam_deploy/stage1_color_v6_send.py', 'B': '视觉/src/maixcam_deploy/v6_bridge.py',
    'I': '电控/src/electrical_control/rpi/vision_ingest.py',
    'S': '电控/src/electrical_control/rpi/socket_vision_source.py',
    'R': '电控/deploy/run_chain.py', 'P': '电控/src/electrical_control/rpi/pixel_to_device.py',
    'Q': 'docs/reports/evidence/vision-chain-20260918/chain-probe-output.txt',
    'E': 'docs/reports/evidence/vision-chain-20260918/dataset-models-output.txt',
    'drop_strategy.py': '电控/src/electrical_control/rpi/drop_strategy.py',
    'dataset-models-findings.md': 'docs/reports/evidence/vision-chain-20260918/dataset-models-findings.md',
    'related-tests-output.txt': 'docs/reports/evidence/vision-chain-20260918/related-tests-output.txt',
    'related-tests-workspace-output.txt': 'docs/reports/evidence/vision-chain-20260918/related-tests-workspace-output.txt',
}
text = REPORT.read_text(encoding='utf-8')
citations = []
for m in re.finditer(r'\b([MCVBISRPQE]):(\d+(?:[–,\-]\d+)*)', text):
    citations.append((aliases[m[1]], m[2]))
for chunk in re.findall(r'`([^`\n]+)`', text):
    m = re.fullmatch(r'(.+?):(\d+(?:[–,\-]\d+)*)', chunk)
    if m:
        citations.append((aliases.get(m[1], m[1]), m[2]))
manifest, errors = {}, []
for path, span in citations:
    file = ROOT / path
    if not file.is_file():
        errors.append(f'missing file: {path}:{span}')
        continue
    data = file.read_bytes()
    line_count = len(data.decode('utf-8-sig').splitlines())
    for value in map(int, re.findall(r'\d+', span)):
        if not 1 <= value <= line_count:
            errors.append(f'out of range: {path}:{value}, total={line_count}')
    manifest[path] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'lines': line_count}
for data in [REPORT.read_bytes()]:
    manifest[REPORT.relative_to(ROOT).as_posix()] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
                                                  'lines': len(data.decode('utf-8').splitlines())}
# Detect drift in the exact MaixCAM source used by the executable probe.
for line in (HERE / 'chain-probe-output.txt').read_text(encoding='utf-8').splitlines():
    if line.startswith('extracted_source: '):
        record = json.loads(line.split(': ', 1)[1])
        actual = hashlib.sha256((ROOT / record['path']).read_bytes()).hexdigest()
        if actual != record['sha256']:
            errors.append('probe source changed: ' + record['path'])
result = {'timestamp': datetime.now().astimezone().isoformat(), 'citations_checked': len(citations),
          'files': len(manifest), 'errors': errors,
          'note': 'Range/existence/hash check only; semantic review is in independent-review.md'}
(HERE / 'report-check-output.txt').write_text('command=py -3 docs/reports/evidence/vision-chain-20260918/verify_report.py\n'
    + json.dumps(result, ensure_ascii=False, indent=2) + '\nexit_code=' + str(bool(errors) * 1) + '\n', encoding='utf-8')
check_path = (HERE / 'report-check-output.txt').relative_to(ROOT).as_posix()
if check_path in manifest:
    check_data = (HERE / 'report-check-output.txt').read_bytes()
    manifest[check_path] = {'sha256': hashlib.sha256(check_data).hexdigest(), 'bytes': len(check_data),
                            'lines': len(check_data.decode('utf-8').splitlines())}
(HERE / 'source-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(bool(errors) * 1)
