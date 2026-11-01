#!/bin/sh
# 查 MaixCAM 上能不能显示中文（找字体 + 测 MaixPy 字体 API）
#
# 用法：ssh root@172.20.10.9 "sh /root/probe_font.sh"

echo "=============================================================="
echo "  MaixCAM 中文字体探测"
echo "=============================================================="

echo
echo "=== 1) /usr/share/fonts ==="
ls -la /usr/share/fonts/ 2>/dev/null || echo "  不存在"

echo
echo "=== 2) 常见字体目录 ==="
for d in /usr/share/fonts /usr/local/share/fonts /root/fonts /mnt/data/fonts /system/fonts; do
    if [ -d "$d" ]; then
        echo "  [$d]"
        ls "$d" 2>/dev/null | head -10 | sed 's/^/    /'
    fi
done

echo
echo "=== 3) 全盘找 ttf/ttc（限时）==="
timeout 15 find /usr /root /mnt /system -name '*.ttf' -o -name '*.ttc' 2>/dev/null | head -20
echo "  （若无输出说明没有字体文件）"

echo
echo "=== 4) MaixPy image 模块里的字体相关 API ==="
python3 - <<'PYEOF' 2>&1 | grep -Ev "^--|Maix Comm|pinmap|listening" | sed 's/^/  /'
try:
    from maix import image
    names = [x for x in dir(image) if 'font' in x.lower()]
    print("字体相关名字: %s" % names)
    # 试着看看有没有 load_font
    if hasattr(image, 'load_font'):
        print("has image.load_font  => 可以加载 TTF")
    else:
        print("NO image.load_font")
    # Image 类上有没有 draw_string
    print("Image.draw_string: %s" % hasattr(image.Image, 'draw_string'))
except Exception as e:
    print("导入失败: %s" % e)
PYEOF

echo
echo "=== 5) 试加载中文字体（如果有）==="
python3 - <<'PYEOF' 2>&1 | grep -Ev "^--|Maix Comm|pinmap|listening" | sed 's/^/  /'
from maix import image
import glob
cands = glob.glob('/usr/share/fonts/**/*.ttf', recursive=True) + \
        glob.glob('/usr/share/fonts/**/*.ttc', recursive=True) + \
        glob.glob('/root/**/*.ttf', recursive=True)
print("候选字体: %s" % (cands[:5] if cands else "无"))
if cands and hasattr(image, 'load_font'):
    try:
        f = image.load_font(cands[0], size=20)
        print("load_font OK: %s" % cands[0])
        img = image.Image(200, 60)
        img.draw_string(2, 2, "正方体", font=f, color=image.COLOR_WHITE)
        print("draw_string 中文调用成功")
    except Exception as e:
        print("失败: %s" % e)
else:
    print("跳过（无字体文件或无 load_font）")
PYEOF

echo
echo "=============================================================="
echo "  结论"
echo "=============================================================="
echo "  若有 ttf/ttc 且有 load_font  -> 中文可显示"
echo "  否则 -> 需要从 PC 传一个中文字体上去"
echo "=============================================================="
