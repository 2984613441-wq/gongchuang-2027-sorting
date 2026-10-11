"""Read-only source search; append a local, timestamped evidence package."""
import collections
import datetime as dt
import difflib
import hashlib
import json
import pathlib
import re
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
CORE = pathlib.Path(r'C:\Users\29845\AI-KINGDOM-PORTABLE-CORE')
ROOTS = [CORE / 'projects/ai-kingdom-continuity', CORE / 'nodes/deepseek']
TERMS = ['AUDIT4', 'CHECK 1', 'R3-14', '6 PASS / 5 PARTIAL / 3 NOT FIXED']
OUT = HERE / ('readonly-search-' + dt.datetime.now().strftime('%Y%m%dT%H%M%S%f'))
OUT.mkdir()
def sha(b):
    return hashlib.sha256(b).hexdigest().upper()
def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

command = ['rg', '-n', '--hidden', '--no-ignore', '-i', '-F']
for term in TERMS:
    command += ['-e', term]
command += list(map(str, ROOTS))
run = subprocess.run(command, capture_output=True, encoding='utf-8')
save('RG-RESULT.json', {'command': command, 'exit_code': run.returncode,
                        'stdout': run.stdout, 'stderr': run.stderr})
files, errors, data = [], [], {}
for root in ROOTS:
    for p in sorted(root.rglob('*')):
        if not p.is_file():
            continue
        try:
            before = p.stat()
            raw = p.read_bytes()
            after = p.stat()
            text = raw.decode('utf-8-sig')
            rel = str(p.relative_to(CORE))
            data[rel] = raw
            target = OUT / 'snapshot' / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            files.append({'path': str(p), 'relative_to_core': rel, 'sha256': sha(raw),
                          'bytes': len(raw), 'mtime_utc': dt.datetime.fromtimestamp(after.st_mtime, dt.timezone.utc).isoformat(),
                          'ctime_utc': dt.datetime.fromtimestamp(after.st_ctime, dt.timezone.utc).isoformat(),
                          'stable_during_read': (before.st_mtime_ns, before.st_size) == (after.st_mtime_ns, after.st_size),
                          'filename_matches': [t for t in TERMS if t.lower() in p.name.lower()],
                          'content_matches': [{'term': t, 'line': n, 'text': line}
                                              for n, line in enumerate(text.splitlines(), 1)
                                              for t in TERMS if t.lower() in line.lower()]})
        except (OSError, UnicodeError) as exc:
            errors.append({'path': str(p), 'error': str(exc)})

baseline_bytes = (HERE / 'BASELINE.json').read_bytes()
baseline = json.loads(baseline_bytes.decode('utf-8-sig'))
old = {f['path']: f['sha256'] for f in baseline['files']}
project = {str(pathlib.Path(f['path']).relative_to(ROOTS[0])): f['sha256']
           for f in files if ROOTS[0] in pathlib.Path(f['path']).parents}
drift = [{'path': p, 'baseline': old.get(p), 'current': project.get(p)}
         for p in sorted(set(old) | set(project)) if old.get(p) != project.get(p)]
for entry in drift:
    path = entry['path']
    prev = HERE / 'baseline' / path
    current = ROOTS[0] / path
    a = prev.read_text(encoding='utf-8-sig').splitlines(True) if prev.exists() else []
    b = current.read_text(encoding='utf-8-sig').splitlines(True) if current.exists() else []
    dest = OUT / 'diffs' / (path + '.diff')
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(''.join(difflib.unified_diff(a, b, fromfile='baseline/' + path, tofile='current/' + path)), encoding='utf-8')

events = [json.loads(line) for line in data[str(ROOTS[0].relative_to(CORE) / 'events.jsonl')].splitlines() if line.strip()]
counts = collections.Counter(e['event_id'] for e in events)
manifest_results = []
for line in data[str(ROOTS[0].relative_to(CORE) / 'MANIFEST-SHA256.txt')].decode('utf-8-sig').splitlines():
    m = re.match(r'^([A-Fa-f0-9]{64})\s+(\d+)\s+(.+)$', line)
    if m:
        expected, size, name = m.groups()
        p = pathlib.Path(name)
        if not p.is_absolute():
            p = CORE / p
        raw = p.read_bytes() if p.is_file() else None
        manifest_results.append({'path': str(p), 'expected': expected, 'current': sha(raw) if raw is not None else None,
                                 'matches': raw is not None and sha(raw) == expected and len(raw) == int(size)})

end_changes = []
for f in files:
    p = pathlib.Path(f['path'])
    if not p.exists() or sha(p.read_bytes()) != f['sha256']:
        end_changes.append(str(p))
end_set = {str(p) for root in ROOTS for p in root.rglob('*') if p.is_file()}
end_changes += sorted(end_set - {f['path'] for f in files})
status = 'MISSING_SOURCE'
if errors or run.returncode not in (0, 1) or end_changes:
    status = 'SEARCH_INCOMPLETE'
if any(m['term'] != 'R3-14' for f in files for m in f['content_matches']) or any(f['filename_matches'] for f in files):
    status = 'CANDIDATE_REQUIRES_REVIEW'
result = {'observed_at': dt.datetime.now().astimezone().isoformat(), 'audit4_evidence_status': status,
          'searched_roots': list(map(str, ROOTS)), 'terms': TERMS, 'files': files, 'errors': errors,
          'baseline_sha256': sha(baseline_bytes), 'baseline_changes': drift, 'changes_during_search': end_changes,
          'shared_files_written_by_this_script': 0,
          'events_count': len(events), 'unique_ids': len(counts),
          'duplicate_ids': {k: v for k, v in counts.items() if v > 1},
          'ev0022_present': 'EV-20260925-DSH-0022' in counts,
          'manifest': manifest_results}
save('SEARCH-EVIDENCE.json', result)
report = ['# 第四轮报告定向检索（只读）', '', f'- evidence_status: `{status}`',
          f'- 观察时间：{result["observed_at"]}；文件时间仅为文件系统元数据，不证明事件发生时间。',
          '- 共享文件修改：0；B-1–B-5 均未修订。不依据第四轮结论转述采取修复。',
          f'- 原 BASELINE.json 保留不变，SHA256：`{sha(baseline_bytes)}`。',
          f'- 项目基线差异：{len(drift)}；检索期间文件变化：{len(end_changes)}；读取错误：{len(errors)}。',
          '- 命令：`python search_audit4.py`；内部 rg 命令、退出码和完整原始输出见 RG-RESULT.json。',
          '', '## 实际检查路径', ''] + [f'- `{p}`（递归、包括隐藏文件、不使用忽略规则）' for p in ROOTS]
report += ['', f'共逐文件读取 {len(files)} 个文件，逐字节快照保存在本包 snapshot/。原基线未刷新。', '',
           '| 关键词（不区分大小写） | 文件名命中 | 正文命中行数 |', '| --- | ---: | ---: |']
for term in TERMS:
    report.append(f'| `{term}` | {sum(term in f["filename_matches"] for f in files)} | {sum(m["term"] == term for f in files for m in f["content_matches"])} |')
report += ['', '## 命中文件的内容判别', '',
           '- EVIDENCE-TEST-20260925-AUDIT3.md：标题、test_id、审计者标识均明确为第三轮，末尾要求未来第四轮验证；不是第四轮。',
           '- EVIDENCE-TEST-20260925-RETEST.md：第二轮复测正文，末尾补充引用第三轮；不是第四轮。',
           '- STATE.md：S16 引用第三轮，S17 明示修复后尚未经第四轮独立验证；不是审计报告。',
           '- INDEX.md：编号命名空间中引用第三轮 R3-1–R3-14；不是审计报告。',
           '- 未找到独立的第四轮报告正文，不能根据文件修改时间推断它属于第四轮。',
           '', '## 现有缺陷只读复核', '',
           f'- 事件 {len(events)} 条、唯一 ID {len(counts)} 个、重复 ID {sum(v > 1 for v in counts.values())} 个；EV-0022 存在：{result["ev0022_present"]}。',
           f'- 旧清单匹配 {sum(r["matches"] for r in manifest_results)}/{len(manifest_results)}。',
           '- RECEIPT 的 D-008–D-012 提议范围、三条未来时间事件及权威副本冲突保持未修状态；未把当前时间或 mtime 写成历史事件时间。',
           '- 真实压缩恢复及 H-20260925-DSH-001 跨节点接收仍为 PARTIAL；本轮未执行，不作整体 PASS 判断。',
           '', '## 完整文件路径、时间、哈希', '', '| 实际检查路径 | mtime UTC | SHA256 |', '| --- | --- | --- |']
report += [f'| `{f["path"]}` | {f["mtime_utc"]} | `{f["sha256"]}` |' for f in files]
report += ['', '各命中原文及行号、文件 ctime/mtime、逐项清单差异见 SEARCH-EVIDENCE.json。取得报告正文后再继续修复；当前状态为等待来源，不请求重复授权。', '']
(OUT / 'REPORT.md').write_text('\n'.join(report), encoding='utf-8')
print(json.dumps({'output': str(OUT), 'status': status, 'files_checked': len(files), 'baseline_changes': drift,
                  'during_search_changes': end_changes, 'errors': errors,
                  'matches': {term: sum(m['term'] == term for f in files for m in f['content_matches']) for term in TERMS}}, ensure_ascii=False))
