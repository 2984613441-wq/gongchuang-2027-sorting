#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 派工-2026-09-21/ 下的提示词文件生成为一个自包含的「派工看板」HTML。

用法（在本工作区根目录）：
    py -3 工具/生成派工看板-20260921.py

产出：派工-2026-09-21/派工看板.html
    单文件、无外部依赖、无网络请求；打开即用，每个 AI 一份，可一键复制或下载 .txt。

设计要点（与 生成派工看板.py 一致，避免踩过的坑）：
  · 正文全部经 JSON 注入 + textContent 渲染，**不做 HTML 转义**，
    避免提示词里的 ``` / < > & 被吃掉或造成注入。
  · 顺序由 ORDER 决定；不在 ORDER 里的文件排在最后（按文件名）。
"""

import json
import pathlib
import sys

SRC_DIR = pathlib.Path(__file__).resolve().parent.parent / "派工-2026-09-21"
OUT = SRC_DIR / "派工看板.html"

# 展示顺序：文件名 -> (按钮短名, 目标 AI, 附件提示, 一句话任务)
META = {
    "00-总控索引与分工.md": (
        "00 总控索引", "你自己看", "", "背景 / 分工 / 红线 / 怎么回收"),
    "01-T1-视觉-物体必须完整在画面内.md": (
        "01 T1 视觉", "最强视觉那家（Codex/Claude）", "",
        "修「物体有一部分出画面就识别不到」"),
    "02-T2-固件-派发时序与NACK根因.md": (
        "02 T2 固件时序", "Codex", "",
        "NACK_SINGLE_TASK_ONLY 根因 + 正确派发时序"),
    "03-T3-标定-XY行程与落点操作卡.md": (
        "03 T3 标定操作卡", "Claude", "",
        "给朋友的操作卡：量 X/Y 实际行程 + 落点标定 SOP"),
    "04-T4-机械-3落点与转盘2方向.md": (
        "04 T4 机械/转盘", "Grok", "",
        "3 个固定落点 + 转盘只转 2 个方向（0°/180°）"),
    "05-T5-夹爪-只动两次的行为确认.md": (
        "05 T5 夹爪", "DeepSeek", "",
        "「夹爪每件只动两次」是设计还是故障 + 改法"),
    "06-T6-性能-屏幕帧打包提速.md": (
        "06 T6 屏幕提速", "ChatGPT", "",
        "逐像素打包 → numpy/Pillow，附逐字节 md5 对拍"),
    "07-T7-评审-对抗性复核.md": (
        "07 T7 评审", "与执行者不同的模型", "",
        "对上列全部产出做对抗性复核"),
    "08-必读补充-跟任一份一起发.md": (
        "08 必读补充", "全部都要发", "",
        "★最新事实：行程/坐标口径/Y优先/货格/15秒语义 —— 跟任一份一起发"),
}

HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>派工看板 · 2026-09-21</title>
<style>
:root{--bg:#0f1115;--panel:#171a21;--line:#2a2f3a;--fg:#e6e9ef;--dim:#9aa3b2;--acc:#4f9cf9;--ok:#3fb950;--warn:#d29922}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
header{padding:18px 22px;border-bottom:1px solid var(--line);background:var(--panel)}
h1{margin:0 0 6px;font-size:18px}
.sub{color:var(--dim);font-size:13px}
.wrap{display:flex;min-height:calc(100vh - 74px)}
nav{width:250px;flex:0 0 250px;border-right:1px solid var(--line);padding:12px;overflow:auto;background:var(--panel)}
nav button{display:block;width:100%;text-align:left;margin:0 0 6px;padding:9px 11px;border-radius:8px;
  border:1px solid var(--line);background:#1d2129;color:var(--fg);cursor:pointer;font-size:13px}
nav button:hover{border-color:var(--acc)}
nav button.on{background:#12325c;border-color:var(--acc)}
nav .who{display:block;color:var(--dim);font-size:11px;margin-top:2px}
main{flex:1;padding:16px 20px;min-width:0}
.bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.bar button{padding:8px 14px;border-radius:8px;border:1px solid var(--line);background:#1d2129;color:var(--fg);cursor:pointer}
.bar button.primary{background:#12325c;border-color:var(--acc)}
.bar .meta{color:var(--dim);font-size:12px}
pre{margin:0;padding:16px;border:1px solid var(--line);border-radius:10px;background:#0b0d11;
  white-space:pre-wrap;word-break:break-word;font:13px/1.6 "Cascadia Mono",Consolas,monospace;max-height:calc(100vh - 210px);overflow:auto}
.toast{position:fixed;right:18px;bottom:18px;padding:10px 16px;border-radius:8px;background:var(--ok);color:#04120a;
  font-weight:600;opacity:0;transition:.25s;pointer-events:none}
.toast.on{opacity:1}
</style>
</head>
<body>
<header>
  <h1>派工看板 · 2026-09-21</h1>
  <div class="sub">点左边选一份 → 点「复制」→ 整份贴给对应的 AI。所有提示词都带只读条款，AI 不会碰你的文件。</div>
</header>
<div class="wrap">
  <nav id="nav"></nav>
  <main>
    <div class="bar">
      <button class="primary" id="copy">📋 复制这一份</button>
      <button id="dl">⬇ 下载 .txt</button>
      <button id="all">复制全部（含分隔线）</button>
      <span class="meta" id="meta"></span>
    </div>
    <pre id="body"></pre>
  </main>
</div>
<div class="toast" id="toast">已复制</div>
<script>
const DOCS = __DOCS__;
const ORDER = __ORDER__;
let cur = 0;
const nav = document.getElementById('nav');
const bodyEl = document.getElementById('body');
const metaEl = document.getElementById('meta');

function labelOf(d){ return d.button + (d.who ? ' · ' + d.who : ''); }

ORDER.forEach((i, n) => {
  const d = DOCS[i];
  const b = document.createElement('button');
  b.innerHTML = '';
  b.appendChild(document.createTextNode(d.button));
  const s = document.createElement('span');
  s.className = 'who';
  s.textContent = d.who + (d.task ? ' · ' + d.task : '');
  b.appendChild(s);
  b.onclick = () => show(n);
  nav.appendChild(b);
});

function show(n){
  cur = n;
  const d = DOCS[ORDER[n]];
  bodyEl.textContent = d.text;
  metaEl.textContent = '目标：' + (d.who || '—') + (d.attach ? ' ｜ ' + d.attach : '');
  [...nav.children].forEach((b, i) => b.classList.toggle('on', i === n));
}

function toast(msg){
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('on');
  setTimeout(() => t.classList.remove('on'), 1100);
}

async function copyText(txt, msg){
  try { await navigator.clipboard.writeText(txt); toast(msg || '已复制'); }
  catch (e) {
    const ta = document.createElement('textarea');
    ta.value = txt; document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); ta.remove(); toast(msg || '已复制');
  }
}

document.getElementById('copy').onclick = () => copyText(DOCS[ORDER[cur]].text);
document.getElementById('dl').onclick = () => {
  const d = DOCS[ORDER[cur]];
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([d.text], {type:'text/plain;charset=utf-8'}));
  a.download = d.file.replace(/\\.md$/, '.txt');
  a.click(); URL.revokeObjectURL(a.href);
};
document.getElementById('all').onclick = () => {
  const joined = ORDER.map(i => DOCS[i].text).join('\\n\\n\\n' + '='.repeat(78) + '\\n\\n\\n');
  copyText(joined, '已复制全部');
};

show(0);
</script>
</body>
</html>
"""


def collect():
    if not SRC_DIR.exists():
        sys.exit(f"目录不存在: {SRC_DIR}")
    files = sorted(p for p in SRC_DIR.glob("*.md"))
    if not files:
        sys.exit(f"{SRC_DIR} 里没有 .md")

    by_name = {p.name: p for p in files}
    order_names = [n for n in META if n in by_name]
    rest = [p.name for p in files if p.name not in META]
    if rest:
        print("⚠️ 下列文件不在 META 里，已排到最后：", ", ".join(rest))
    order_names += rest

    docs = []
    for name in order_names:
        p = by_name[name]
        text = p.read_text(encoding="utf-8")
        button, who, attach, task = META.get(name, (p.stem, "", "", ""))
        docs.append({
            "file": name, "button": button, "who": who,
            "attach": attach, "task": task, "text": text,
        })
    order = list(range(len(docs)))
    return docs, order


def main():
    docs, order = collect()
    html = (HTML
            .replace("__DOCS__", json.dumps(docs, ensure_ascii=False))
            .replace("__ORDER__", json.dumps(order)))
    OUT.write_text(html, encoding="utf-8")
    print(f"✅ 已生成 {OUT}  ({OUT.stat().st_size} 字节, {len(docs)} 份提示词)")
    for d in docs:
        print(f"   · {d['button']:<22} → {d['who'] or '—':<24} {len(d['text'])} 字符")
    return 0


if __name__ == "__main__":
    sys.exit(main())
