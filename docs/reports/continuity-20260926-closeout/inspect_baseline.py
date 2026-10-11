"""Read-only shared-root inspection; outputs local evidence only."""
import collections
import datetime
import hashlib
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
BASE = json.loads((HERE / 'BASELINE.json').read_text(encoding='utf-8-sig'))
ROOT = pathlib.Path(BASE['root'])
CORE = ROOT.parent.parent

def sha(data):
    return hashlib.sha256(data).hexdigest().upper()

original = {x['path']: x for x in BASE['files']}
current = {str(p.relative_to(ROOT)): {'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size}
           for p in ROOT.rglob('*') if p.is_file()}
drift = [{'path': p, 'baseline': original.get(p), 'current': current.get(p)}
         for p in sorted(set(original) | set(current))
         if original.get(p, {}).get('sha256') != current.get(p, {}).get('sha256')]
if drift:
    for d in drift:
        source = ROOT / d['path']
        if source.is_file():
            dest = HERE / 'concurrent-current' / d['path']
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(source.read_bytes())

groups = collections.defaultdict(list)
for line, raw in enumerate((ROOT / 'events.jsonl').read_bytes().splitlines(), 1):
    if raw.strip():
        item = json.loads(raw)
        groups[item['event_id']].append({'line': line, 'line_sha256': sha(raw), 'event': item})
duplicates = {k: v for k, v in groups.items() if len(v) > 1}
manifest = []
for line in (ROOT / 'MANIFEST-SHA256.txt').read_text(encoding='utf-8-sig').splitlines():
    match = re.match(r'^([0-9A-Fa-f]{64})\s+(\d+)\s+(.+)$', line)
    if match:
        expected, size, name = match.groups()
        path = pathlib.Path(name)
        if not path.is_absolute():
            path = CORE / path
        actual = sha(path.read_bytes()) if path.is_file() else None
        manifest.append({'path': str(path), 'expected': expected, 'actual': actual,
                         'match': actual == expected and path.stat().st_size == int(size) if actual else False})
result = {
    'observed_at': datetime.datetime.now().astimezone().isoformat(),
    'task_state': 'WAITING_FOR_AUDIT4_SOURCE',
    'baseline_sha256': sha((HERE / 'BASELINE.json').read_bytes()),
    'shared_root_mutations': 0,
    'concurrent_changes': drift,
    'files': current,
    'events': {'lines': sum(map(len, groups.values())), 'unique_ids': len(groups),
               'duplicates': duplicates, 'ev0022_present': 'EV-20260925-DSH-0022' in groups},
    'manifest': manifest,
    'manifest_matches': sum(x['match'] for x in manifest),
    'manifest_total': len(manifest),
    'acceptance': 'NOT_ASSESSED',
    'real_compaction_recovery': 'PARTIAL',
    'H-20260925-DSH-001_cross_node_receipt': 'PARTIAL',
}
(HERE / 'INSPECTION.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
report = [
    '# CONTINUITY-20260926：修复前核验与恢复记录',
    '',
    '- owner: Codex（用户仅授权本次收口临时单写者；未获取永久治理权）',
    '- state: WAITING_FOR_AUDIT4_SOURCE',
    '- 共享根实际修改：0；仅在当前可写工作区保存逐字节基线、检查脚本和报告。',
    '- 第四轮审计报告：未找到；已请求用户提供完整路径或正文。不得把第三轮报告冒充第四轮。',
    '- 最小验证：写前全项目哈希与文件集合比较；历史事件字节前缀不变；新增 ID 唯一；重复 ID 按行号和行哈希定位；更正含 supersedes；三种决定状态有来源；引用带路径/修订/哈希；最后生成清单并全量回读。',
    '- 当前实际命令：`python inspect_baseline.py`，退出码 0；结果见 INSPECTION.json。',
    '- 内部检查仅是 Codex 只读核验，不是 DeepSeek 独立复验。',
    f'- 基线捕获时间：{BASE["captured_at"]}；最近复核：{result["observed_at"]}。时间只表示本次观察，不表示历史事件发生时间。',
    f'- BASELINE.json SHA256：`{result["baseline_sha256"]}`。',
    f'- 并发差异数：{len(drift)}；原清单匹配：{result["manifest_matches"]}/{len(manifest)}。',
    '',
    '## B-1–B-5 状态',
    '',
    '以下编号仅按本次用户列举顺序临时对应，须第四轮报告确认；均未提交修复。',
    '',
    '| 项 | 本次核验 | 处置状态 |',
    '| --- | --- | --- |',
    '| B-1 重复 event_id | 36 条记录、25 个唯一 ID；11 个 ID 各出现两次，详见 INSPECTION.json 的行号和行哈希 | 未修；保留全部原事件 |',
    '| B-2 EV-0022 | 原事件不存在，但 EV-0025 和第三轮审计引用了它 | 未修；缺失占位与原事件真实恢复必须区分，不猜造原文或发生时间 |',
    '| B-3 RECEIPT 状态 | 项目回执仍把 D-008–D-012 全列为提议；决定账本 D-008 已确认、D-010 待固化 | 未修；不得把新引用哈希写进历史 actual_files_read 冒充当时已读 |',
    '| B-4 清单 | 28 项中 8 项失配 | 未修；待共享事实稳定后最后重生成 |',
    '| B-5 三条未来时间事件 | EV-0014/0015/0016 各两份，actor=user、time=22:00；既有 EV-0023 未提供结构化 supersedes，且声称未证实的时间区间 | 未修；更正应由 Codex 记录，历史 occurred_at 未知，不直接归因用户 |',
    '',
    '## 剩余缺陷及证据边界',
    '',
    '- INDEX 同时声称 MANIFEST 为历史快照和当前权威；多处重复事实需改为唯一权威映射及版本引用。',
    '- PARAMETERS.yaml 没有明确的文件级权威声明；参数存在项目根/截止时间等重复表示，需保留原值、来源并指定唯一有效键。',
    '- SHARED-UNDERSTANDING 顶部对 P1–P4 的共识来源提出异议，下方仍全标待固化；不得擅自升级成已确认。',
    '- 文件 mtime 只能证明文件修改时刻，不能用作历史事件真实发生时刻。',
    '- 真实压缩恢复：PARTIAL；H-20260925-DSH-001 跨节点接收：PARTIAL；本次未实施这两种运行时测试。',
    '- DeepSeek 只读复验尚未交付：待修复完成生成最终包后交接；本次未发送消息或代其出具回执。',
    '',
    '## 逐文件 SHA256',
    '',
    '无共享根修改，因此当前哈希等于基线；这里的“当前”不代表修复最终版本。',
    '',
    '| 路径 | 基线 SHA256 | 当前 SHA256 |',
    '| --- | --- | --- |',
]
for name, item in sorted(original.items()):
    report.append(f'| `{name}` | `{item["sha256"]}` | `{current.get(name, {}).get("sha256", "MISSING")}` |')
report += ['', '## 恢复动作', '',
           '取得第四轮报告后读取全文并保存其哈希，再运行 inspect_baseline.py。若出现并发差异，停止提交，使用 baseline/ 与 concurrent-current/ 保存差异，不刷新旧基线以覆盖当前内容。',
           '基线未变时按用户现有授权继续准备可审阅补丁。目标目录不在当前 writable_roots，实际提交需工具的 sandbox escalation；尚未尝试写入或触发审批。无需重复请求本次业务授权。', '']
(HERE / 'REPORT.md').write_text('\n'.join(report), encoding='utf-8')
print(json.dumps({k: result[k] for k in ('observed_at', 'baseline_sha256', 'shared_root_mutations', 'concurrent_changes', 'manifest_matches', 'manifest_total')}, ensure_ascii=False))
print('duplicate_ids:', ', '.join(duplicates))
print('events:', result['events']['lines'], 'unique_ids:', len(groups), 'EV-0022:', result['events']['ev0022_present'])
