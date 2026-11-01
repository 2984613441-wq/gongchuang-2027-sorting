#!/bin/sh
# 列出 MaixPy image 模块里所有可用的 COLOR_* 常量
echo "=== 可用颜色常量 ==="
python3 - <<'PYEOF' 2>&1 | grep -Ev "^--|Maix Comm|pinmap|listening"
from maix import image
cols = sorted(x for x in dir(image) if x.startswith('COLOR'))
print("共 %d 个:" % len(cols))
for c in cols:
    print("  %s" % c)
print()
# 逐个测试我脚本里用到的
NEED = ['COLOR_GREEN', 'COLOR_ORANGE', 'COLOR_RED', 'COLOR_PURPLE',
        'COLOR_CYAN', 'COLOR_YELLOW', 'COLOR_WHITE', 'COLOR_BLACK', 'COLOR_BLUE']
print("脚本需要的:")
for n in NEED:
    ok = hasattr(image, n)
    print("  %-16s %s" % (n, "OK" if ok else "MISSING"))
PYEOF
