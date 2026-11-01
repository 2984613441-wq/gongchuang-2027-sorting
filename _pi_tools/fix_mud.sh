#!/bin/bash
# 修正 yolo11n_8c_448.mud 的 UTF-8 BOM（BOM 会让 MaixPy 解析 .mud 失败，err 5）
set -u
F=/root/my_models/yolo11n_8c_448.mud

echo "=== 修正前前 3 字节 ==="
head -c 3 "$F" | od -An -tx1

# 用 python 安全重写（去掉 BOM，并去掉可能存在的 CR）
python3 - "$F" <<'PYEOF'
import sys, io
p = sys.argv[1]
raw = open(p, "rb").read()
# 去 UTF-8 BOM
if raw.startswith(b"\xef\xbb\xbf"):
    raw = raw[3:]
    print("  已移除 UTF-8 BOM")
# 去 CR（Windows 换行）
if b"\r" in raw:
    raw = raw.replace(b"\r", b"")
    print("  已移除 CR")
# 规范化空白
text = raw.decode("utf-8", "replace").strip()
lines = [ln.rstrip() for ln in text.split("\n")]
out = "\n".join(lines) + "\n"
open(p, "w", encoding="utf-8", newline="\n").write(out)
print("  写入 %d 字节" % len(out.encode("utf-8")))
PYEOF

echo
echo "=== 修正后前 3 字节 ==="
head -c 3 "$F" | od -An -tx1
echo "=== 内容 ==="
cat "$F"
echo "=== 校验 ==="
python3 - "$F" <<'PYEOF'
import sys
p = sys.argv[1]
raw = open(p, "rb").read()
assert not raw.startswith(b"\xef\xbb\xbf"), "仍有 BOM"
assert b"\r" not in raw, "仍有 CR"
assert raw.startswith(b"["), "第一字节不是 '['"
print("  ✅ 无 BOM、无 CR、以 '[' 开头")
PYEOF
