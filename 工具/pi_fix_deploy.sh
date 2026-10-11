#!/bin/bash
# 修复 Python 3.9 不兼容的 slots=True，并隔离树莓派上的冗余副本
set -u

echo "=== 1. 修复 slots=True（Python 3.9 不支持）==="
python3 - <<'PY'
import io, os, re, sys

root = "/home/pi/电控/src"
pat = re.compile(r"@dataclass\(([^)]*)\)")
total = 0
for dirpath, _dirs, files in os.walk(root):
    if "__pycache__" in dirpath:
        continue
    for name in files:
        if not name.endswith(".py"):
            continue
        p = os.path.join(dirpath, name)
        with io.open(p, "r", encoding="utf-8") as f:
            src = f.read()
        if "slots" not in src:
            continue

        def fix(m):
            global total
            args = m.group(1)
            # 去掉 slots=... 参数（保留其余参数）
            parts = [a.strip() for a in args.split(",") if a.strip()]
            kept = [a for a in parts if not a.startswith("slots")]
            if len(kept) == len(parts):
                return m.group(0)
            total += 1
            return "@dataclass(" + ", ".join(kept) + ")"

        new = pat.sub(fix, src)
        if new != src:
            with io.open(p, "w", encoding="utf-8") as f:
                f.write(new)
            print("FIXED:", p)

print("slots= 参数移除处数:", total)
PY

echo
echo "=== 2. 复查是否还有 slots=True 残留 ==="
sudo grep -rnE '@dataclass.*slots[[:space:]]*=' /home/pi/电控/src 2>/dev/null || echo "  无残留 ✅"

echo
echo "=== 3. import 实测（Python 3.9.2）==="
env PYTHONPATH=/home/pi/电控/src python3 - <<'PY'
import importlib, sys, traceback
mods = ["electrical_control",
        "electrical_control.state_machine.core",
        "electrical_control.rpi.display_hdmi",
        "electrical_control.rpi.display",
        "electrical_control.rpi.vision_ingest",
        "electrical_control.protocol"]
bad = 0
for m in mods:
    try:
        mod = importlib.import_module(m)
        print("OK  ", m, "->", getattr(mod, "__file__", None))
    except Exception as e:
        bad += 1
        print("FAIL", m, "->", repr(e))
print("RESULT:", "FAIL" if bad else "PASS")
PY

echo
echo "=== 4. 隔离冗余副本（改名，不删除）==="
TAG="quarantine-20260918"
for p in "/home/pi/电控_src" "/home/pi/电控_deploy"; do
  if sudo test -e "$p"; then
    sudo mv -- "$p" "$p.$TAG" && echo "隔离: $p -> $p.$TAG"
  fi
done
if sudo test -e /opt/ec-chain; then
  sudo mv -- /opt/ec-chain "/opt/ec-chain.$TAG" && echo "隔离: /opt/ec-chain -> /opt/ec-chain.$TAG"
fi

echo
echo "=== 5. 隔离后复查：还剩哪些 electrical_control ==="
sudo find /home/pi /opt -type f -path '*/electrical_control/__init__.py' \
  ! -path '*quarantine*' ! -path '*.bak-*' 2>/dev/null

echo
echo "=== 6. 隔离后还剩哪些 run_chain.py ==="
sudo find /home/pi /opt -name 'run_chain.py' \
  ! -path '*quarantine*' ! -path '*.bak-*' 2>/dev/null
