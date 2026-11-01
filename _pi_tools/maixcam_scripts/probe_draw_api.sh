#!/bin/sh
# 检查 MaixPy 绘制 API 的真实签名，避免下一个 AttributeError / TypeError
echo "=== py_compile 语法检查 ==="
python3 -m py_compile /root/yolo_v7_cn_view.py && echo "  ✅ 语法通过" || echo "  ❌ 语法错误"

echo
echo "=== draw_rect / draw_string 签名 ==="
python3 - <<'PYEOF' 2>&1 | grep -Ev "^--|Maix Comm|pinmap|listening"
from maix import image
import inspect
for fn in ('draw_rect', 'draw_string', 'draw_line', 'draw_circle'):
    f = getattr(image.Image, fn, None)
    if f is None:
        print("  %s: 不存在" % fn)
        continue
    try:
        print("  %s%s" % (fn, inspect.signature(f)))
    except Exception as e:
        print("  %s: 无法读签名 (%s)" % (fn, e))
PYEOF

echo
echo "=== 实测 draw_rect(fill=True) ==="
python3 - <<'PYEOF' 2>&1 | grep -Ev "^--|Maix Comm|pinmap|listening"
from maix import image
img = image.Image(200, 100)
try:
    img.draw_rect(10, 10, 100, 40, color=image.COLOR_BLACK, fill=True)
    print("  ✅ fill=True 可用")
except Exception as e:
    print("  ❌ fill=True 失败: %s" % e)
    try:
        img.draw_rect(10, 10, 100, 40, color=image.COLOR_BLACK, thickness=-1)
        print("  ✅ thickness=-1 可用（fill 的替代）")
    except Exception as e2:
        print("  ❌ thickness=-1 也失败: %s" % e2)
PYEOF
