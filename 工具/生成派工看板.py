#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 派工-多AI并行-2026-09-20/ 下的提示词文件生成为一个自包含的「派工看板」HTML。

用法（在本工作区根目录）：
    py -3 工具/生成派工看板.py

产出：派工-多AI并行-2026-09-20/派工看板.html
   单文件、无外部依赖、无网络请求；打开即用，每个 AI 一份，可一键复制或下载 .txt。

设计要点：正文全部经 JSON 注入 + textContent 渲染，不做 HTML 转义，避免提示词里
的 ``` / < > & 被吃掉或造成注入。
"""

import json
import pathlib
import sys

SRC_DIR = pathlib.Path(__file__).resolve().parent.parent / "派工-多AI并行-2026-09-20"
OUT = SRC_DIR / "派工看板.html"

# 顺序 + 展示元数据： 文件名 -> (按钮短名, 目标 AI, 附件提示, 一句话任务)
META = {
    "00-总控索引与分工.md": (
        "00 总控索引", "你自己看", "", "谁做什么、怎么回收、红线在哪"),
    "01-Codex-T5-T9-固件补丁.md": (
        "01 Codex", "Codex", "", "T5 脉宽白名单补丁 + T9 硬件安全收口"),
    "02a-ClaudeA-T6-T11-评审官.md": (
        "02a Claude-A", "Claude（窗口 1）", "", "T6 夹取策略评审 + T11 方案C 评审"),
    "02b-ClaudeB-T3-屏幕侧问题.md": (
        "02b Claude-B", "Claude（窗口 2）", "", "T3 屏幕侧问题"),
    "07-T13-转盘舵机代码.md": (
        "07 T13 舵机代码", "Claude（同窗口 2）", "", "转盘驱动 + 归零定位状态机 + 自标定"),
    "10-放行消息-给写T13代码的AI.md": (
        "10 T13 放行消息", "给正在写 T13 的 AI（Codex 等）", "",
        "6 条最终裁决：OE→GPIO27 / 内部上拉 / 6 条黑标 / OUTDRV / 时序 / 首次上电"),
    "12-T13改写-GPIO直出版.md": (
        "12 T13 改写·GPIO 直出", "给正在写 T13 的 AI", "",
        "🔴 不用 PCA9685：舵机信号直接 GPIO18 出 PWM + 槽型索引改为挡片"),
    "11-现场诊断求助模板.md": (
        "11 现场诊断求助", "接线卡住时发给任一 AI", "",
        "填空式求助：贴原始输出，要原因排序 + 下一步命令"),
    "03-DeepSeek-T7-T8-时序与语义.md": (
        "03 DeepSeek", "DeepSeek", "可选：附 run_chain.py 全文可提高精度",
        "T7 15秒判据 + T8 落点/时序预算"),
    "04-豆包-T12-T2-赛规与流程.md": (
        "04 豆包", "豆包", "🔴 必须附 27年工创.pdf 第9-13页 + 四川省赛细则 PDF",
        "T12 赛规符合性审查(新) + T2 重标 SOP"),
    "05-Grok-T4-接线单.md": (
        "05 Grok", "Grok", "可选附 PCA9685 板照片 / FC-SPX303Z.pdf",
        "T4 转盘接线单（PWM 扩展板路线）"),
    "06-ChatGPT-T1-几何核算.md": (
        "06 ChatGPT", "ChatGPT", "", "T1 相机位移几何核算 + 现场操作卡"),
    "99-总控汇总与第二轮复核模板.md": (
        "99 总控台", "你自己看", "", "汇总表 / 分歧登记 / 第二轮对抗复核模板"),
}

HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>派工看板 · 多AI并行 · 2026-09-20</title>
<style>
  :root{
    --bg:#f6f7f9; --panel:#fff; --line:#e3e6ea; --ink:#1c1f23; --dim:#6b7280;
    --hi:#2563eb; --ok:#15803d; --warn:#b45309; --warnbg:#fffbeb;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",system-ui,sans-serif}
  header{position:sticky;top:0;z-index:9;background:var(--panel);border-bottom:1px solid var(--line);
         padding:12px 18px;display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
  header h1{margin:0;font-size:16px;font-weight:650}
  header .sub{color:var(--dim);font-size:12.5px}
  header .pill{margin-left:auto;background:#eef2ff;color:var(--hi);border:1px solid #dbe3ff;
               border-radius:999px;padding:3px 11px;font-size:12.5px;font-weight:600}
  .wrap{display:flex;align-items:flex-start;gap:16px;padding:16px 18px 40px;max-width:1500px;margin:0 auto}
  nav{flex:0 0 208px;position:sticky;top:66px;display:flex;flex-direction:column;gap:6px}
  nav button{text-align:left;background:var(--panel);border:1px solid var(--line);border-radius:9px;
             padding:9px 11px;cursor:pointer;font:inherit;color:var(--ink);display:flex;
             align-items:center;gap:8px;transition:.12s}
  nav button:hover{border-color:#c9d2dd}
  nav button.on{border-color:var(--hi);box-shadow:0 0 0 2px #dbe3ff inset;font-weight:600}
  nav button .tick{margin-left:auto;color:var(--ok);font-weight:700;opacity:0;font-size:13px}
  nav button.sent .tick{opacity:1}
  main{flex:1 1 auto;min-width:0;background:var(--panel);border:1px solid var(--line);
       border-radius:12px;padding:16px 18px}
  .hdr{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:4px}
  .hdr h2{margin:0;font-size:16px}
  .ai{background:#f1f5f9;border:1px solid var(--line);border-radius:999px;padding:2px 10px;
      font-size:12.5px;color:var(--dim)}
  .task{color:var(--dim);font-size:13px;margin:2px 0 10px}
  .warn{background:var(--warnbg);border:1px solid #fcd9a4;color:var(--warn);
        border-radius:8px;padding:8px 11px;font-size:13px;margin:0 0 10px}
  .btns{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;align-items:center}
  .btns button{border:1px solid var(--line);background:#fff;border-radius:8px;padding:7px 13px;
               cursor:pointer;font:inherit;font-weight:550;transition:.12s}
  .btns button:hover{border-color:#c9d2dd;background:#fafbfc}
  .btns button.primary{background:var(--hi);border-color:var(--hi);color:#fff}
  .btns button.primary:hover{background:#1d4ed8}
  .btns button.sent{background:#f0fdf4;border-color:#bbf7d0;color:var(--ok)}
  pre{white-space:pre-wrap;word-break:break-word;background:#fbfcfd;border:1px solid var(--line);
      border-radius:10px;padding:14px 15px;margin:0;max-height:calc(100vh - 300px);overflow:auto;
      font:12.5px/1.62 ui-monospace,Consolas,"Cascadia Mono",monospace}
  #toast{position:fixed;left:50%;bottom:28px;transform:translate(-50%,14px);background:#111827;color:#fff;
         padding:9px 16px;border-radius:9px;font-size:13px;opacity:0;pointer-events:none;transition:.18s}
  #toast.on{opacity:1;transform:translate(-50%,0)}
  .foot{color:var(--dim);font-size:12.5px;margin-top:10px}
  @media(max-width:820px){.wrap{flex-direction:column}nav{position:static;flex:none;width:100%;
    flex-direction:row;flex-wrap:wrap}nav button{flex:1 1 auto}pre{max-height:none}}
</style>
</head>
<body>
<header>
  <h1>派工看板 · 多AI并行</h1>
  <span class="sub">2026-09-20 ｜ 点 AI → 复制全文 → 粘进对应会话</span>
  <span class="pill" id="pill"></span>
</header>
<div class="wrap">
  <nav id="nav"></nav>
  <main>
    <div class="hdr"><h2 id="h2"></h2><span class="ai" id="ai"></span></div>
    <div class="task" id="task"></div>
    <div id="warn"></div>
    <div class="btns">
      <button class="primary" id="btnCopy">复制全文</button>
      <button id="btnDl">下载 .txt</button>
      <button id="btnSent">标记已发送</button>
      <span class="foot" id="size"></span>
    </div>
    <pre id="body"></pre>
  </main>
</div>
<div id="toast"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const LS = 'dsh_paigong_sent_20260920';
let sent = new Set();
try { sent = new Set(JSON.parse(localStorage.getItem(LS) || '[]')); } catch (e) {}
let cur = 0;

const $ = id => document.getElementById(id);
function toast(msg){
  const t = $('toast'); t.textContent = msg; t.classList.add('on');
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('on'), 1500);
}
function saveSent(){ try { localStorage.setItem(LS, JSON.stringify([...sent])); } catch (e) {} }

function renderNav(){
  const nav = $('nav'); nav.innerHTML = '';
  DATA.files.forEach((f, i) => {
    const b = document.createElement('button');
    b.textContent = f.label;
    if (sent.has(f.name)) b.classList.add('sent');
    const tick = document.createElement('span');
    tick.className = 'tick'; tick.textContent = '✓';
    b.appendChild(tick);
    b.onclick = () => { cur = i; render(); };
    if (i === cur) b.classList.add('on');
    nav.appendChild(b);
  });
  $('pill').textContent = '已发送 ' + sent.size + ' / ' + DATA.files.length;
}

function render(){
  const f = DATA.files[cur];
  $('h2').textContent = f.label;
  $('ai').textContent = '派给：' + f.ai;
  $('task').textContent = f.task;
  $('warn').innerHTML = '';
  if (f.hint){
    const d = document.createElement('div');
    d.className = 'warn'; d.textContent = f.hint;
    $('warn').appendChild(d);
  }
  $('body').textContent = f.text;
  $('size').textContent = f.text.length.toLocaleString() + ' 字';
  const bs = $('btnSent');
  bs.textContent = sent.has(f.name) ? '✓ 已发送（点击取消）' : '标记已发送';
  bs.className = sent.has(f.name) ? 'sent' : '';
  renderNav();
}

function copy(text){
  // 1) 现代 API（file:// 下有时不可用，故有降级）
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(
      () => toast('已复制 ' + text.length.toLocaleString() + ' 字'),
      () => fallback(text)
    );
    return;
  }
  fallback(text);
  function fallback(t){
    const ta = document.createElement('textarea');
    ta.value = t;
    ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
    document.body.appendChild(ta);
    ta.focus(); ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(ta);
    toast(ok ? '已复制 ' + t.length.toLocaleString() + ' 字'
             : '复制失败，请在下方框内手动全选复制');
  }
}

$('btnCopy').onclick = () => copy(DATA.files[cur].text);

$('btnDl').onclick = () => {
  const f = DATA.files[cur];
  const blob = new Blob([f.text], {type: 'text/plain;charset=utf-8'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = f.name.replace(/\\.md$/, '') + '.txt';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  toast('已下载 ' + a.download);
};

$('btnSent').onclick = () => {
  const n = DATA.files[cur].name;
  sent.has(n) ? sent.delete(n) : sent.add(n);
  saveSent(); render();
};

// 键盘：← → 切换
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') return;
  if (e.key === 'ArrowRight'){ cur = (cur + 1) % DATA.files.length; render(); }
  if (e.key === 'ArrowLeft'){ cur = (cur - 1 + DATA.files.length) % DATA.files.length; render(); }
});

render();
</script>
</body>
</html>
"""


def main() -> int:
    if not SRC_DIR.is_dir():
        print(f"找不到目录：{SRC_DIR}", file=sys.stderr)
        return 1

    files = []
    missing = []
    for name, (label, ai, hint, task) in META.items():
        p = SRC_DIR / name
        if not p.is_file():
            missing.append(name)
            continue
        files.append({
            "name": name,
            "label": label,
            "ai": ai,
            "hint": hint,
            "task": task,
            "text": p.read_text(encoding="utf-8"),
        })

    if missing:
        print("缺文件：" + "、".join(missing), file=sys.stderr)
        return 1
    if not files:
        print("没有可用的提示词文件", file=sys.stderr)
        return 1

    payload = json.dumps({"files": files}, ensure_ascii=False, separators=(",", ":"))
    # 防止正文里出现 </script 提前结束数据块（JSON 里 <\/ 是合法转义）
    payload = payload.replace("</", "<\\/")

    out = HTML.replace("__DATA__", payload)
    OUT.write_text(out, encoding="utf-8", newline="\n")

    total = sum(len(f["text"]) for f in files)
    print(f"OK  {OUT}")
    nbytes = len(out.encode("utf-8"))
    print(f"    {len(files)} 份提示词，正文合计 {total:,} 字，HTML {nbytes:,} 字节")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
