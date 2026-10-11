#!/bin/bash
# Install the Python 3.9 fix on the Raspberry Pi (2026-09-18), DSH via ssh.
# English-only output to avoid console codepage mangling.
set -u
export LC_ALL=C
STAMP=$(date +%Y%m%d-%H%M%S)
SRC=/opt/ec-chain/src
PKG=/home/pi/ec-src-20260918-0200.tar.gz
TMP=/tmp/ecsrc-$STAMP

echo "=== 0. precondition ==="
[ -f "$PKG" ] || { echo "  FAIL: $PKG not found"; exit 1; }
echo "  pkg: $PKG ($(stat -c%s "$PKG") bytes)"

echo ""
echo "=== 1. backup existing src/electrical_control ==="
if [ -d "$SRC/electrical_control" ]; then
  cp -a "$SRC/electrical_control" "$SRC/electrical_control.bak-$STAMP" \
    && echo "  OK backup -> $SRC/electrical_control.bak-$STAMP"
else
  echo "  (absent, skip backup)"
fi

echo ""
echo "=== 2. extract to temp, then copy over ==="
rm -rf "$TMP"; mkdir -p "$TMP"
tar -xzf "$PKG" -C "$TMP" 2>&1 | head -3
if [ ! -d "$TMP/electrical_control" ]; then echo "  FAIL: extract produced nothing"; exit 1; fi
echo "  extracted: $(find "$TMP/electrical_control" -name '*.py' | wc -l) .py files"
cp -a "$TMP/electrical_control/." "$SRC/electrical_control/" \
  && echo "  OK copied into $SRC/electrical_control"
find "$SRC/electrical_control" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
echo "  pycache cleared"

echo ""
echo "=== 3. recheck slots=True residue ==="
N=$(grep -rn "slots=True" "$SRC/electrical_control" 2>/dev/null | wc -l)
echo "  hits: $N  $([ "$N" -eq 0 ] && echo 'PASS' || echo 'FAIL')"

echo ""
echo "=== 4. per-module import test (the key one) ==="
for m in electrical_control electrical_control.protocol electrical_control.rpi \
         electrical_control.scheduler electrical_control.state_machine \
         electrical_control.drivers electrical_control.integration; do
  R=$(PYTHONPATH="$SRC" python3 -c "import $m" 2>&1 | tail -1)
  if [ -z "$R" ]; then echo "  PASS  $m"; else echo "  FAIL  $m"; echo "        $R"; fi
done

echo ""
echo "=== 5. functional smoke: parse_batch_targets (box_id path) ==="
cat > "$TMP/smoke.py" <<'PYEOF'
import sys
from electrical_control.rpi.vision_ingest import parse_batch_targets, BATCH_ID_BYTE_IS_BOX_ID
print("  BATCH_ID_BYTE_IS_BOX_ID =", BATCH_ID_BYTE_IS_BOX_ID)
data = (bytes([2, 0, 1])
        + bytes([1, 90]) + (100).to_bytes(2, 'big') + (200).to_bytes(2, 'big') + bytes([0xFF])
        + bytes([3, 80]) + (300).to_bytes(2, 'big') + (400).to_bytes(2, 'big') + bytes([0xFF]))
bt = parse_batch_targets(data)
print("  parse OK: task_id=%d targets=%d box_ids=%s" % (bt.task_id, len(bt.targets), [t.box_id for t in bt.targets]))
# out-of-range id must be skipped per-item, not raise
data2 = (bytes([2, 0, 1])
         + bytes([0, 90]) + (100).to_bytes(2, 'big') + (200).to_bytes(2, 'big') + bytes([0xFF])
         + bytes([5, 80]) + (300).to_bytes(2, 'big') + (400).to_bytes(2, 'big') + bytes([0xFF]))
bt2 = parse_batch_targets(data2)
print("  skip-test: targets=%d box_ids=%s (expect 1 item, box 5)" % (len(bt2.targets), [t.box_id for t in bt2.targets]))
PYEOF
PYTHONPATH="$SRC" python3 "$TMP/smoke.py" 2>&1 | head -20

echo ""
echo "=== 6. drop_strategy self-check ==="
PYTHONPATH="$SRC" python3 "$SRC/electrical_control/rpi/drop_strategy.py" 2>&1 | tail -8

echo ""
echo "=== 7. permissions for screen work ==="
id pi | tr ',' '\n' | grep -E "video|dialout" || echo "  WARN: pi not in video/dialout group"
ls -la /dev/fb0
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo "  (no USB serial attached)"

echo ""
echo "=== DONE ==="
