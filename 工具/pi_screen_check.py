"""树莓派屏幕部署自检（只读，不装包、不改配置、不上电动作）。

在树莓派上跑（用 run_chain 同款解释器最准）：
    python3 pi_screen_check.py
    /opt/ec-chain/deploy/.venv/bin/python pi_screen_check.py   # 更准：链路实际用的解释器
或从开发机一次性推过去跑：
    ssh pi@<host> 'python3 -' < 工具/pi_screen_check.py

它把 06-屏幕显示 要的 5 样逐项打出来（字体 / 名称表 / 图片目录 / 帧输出 / Pillow），
最后打印一条已填好真实值的 run_chain 启动命令。本脚本只读文件与 /sys。
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# 路径以 电控/deploy/install.sh + ec-chain.service 的 /opt/ec-chain 约定为准，
# /home/pi 是旧约定，一并兜底。
WQY_TTC = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
NAMES_CANDIDATES = ("/opt/ec-chain/names.json", "/home/pi/generated_names.json")
IMAGE_DIR_CANDIDATES = ("/opt/ec-chain/images", "/home/pi/cargo_images")
VENV_PYTHONS = ("/opt/ec-chain/deploy/.venv/bin/python",
                os.path.expanduser("~/电控/deploy/.venv/bin/python"),
                os.path.expanduser("~/deploy/.venv/bin/python"))
CLASS_IDS = range(7)  # image_id == class_id（冻结 1:1）
EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

ok = True

# ssh 管道/Windows 控制台默认不是 UTF-8，中文会变乱码
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def head(title: str) -> None:
    print()
    print("=" * 62)
    print(title)
    print("=" * 62)


def line(label: str, value, verdict: str = "") -> None:
    mark = {"OK": "[OK]  ", "FAIL": "[FAIL]", "WARN": "[WARN]", "": "      "}[verdict]
    print(f"{mark} {label}: {value}")


def font_renders_cjk(font_path: str) -> bool:
    """渲染两个不同汉字比位图；位图相同 = 缺字形（方块）。镜像 control_panel.font_renders_cjk。

    不 import control_panel —— 那是主机 PyQt5 工具，树莓派上不一定装得起来。
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    try:
        font = ImageFont.truetype(font_path, 48)
    except Exception:
        return False

    def glyph(ch: str) -> bytes:
        img = Image.new("L", (96, 96), 0)
        ImageDraw.Draw(img).text((0, 0), ch, font=font, fill=255)
        return img.tobytes()

    return glyph("五") != glyph("棱")


def first_existing(paths) -> str | None:
    for p in paths:
        if Path(p).exists():
            return p
    return None


def check_font() -> str | None:
    global ok
    head("1/5  中文字体（--font）")
    line("解释器", f"{sys.executable} ({platform.python_version()})")
    line("OS", platform.platform())
    rel = Path("/etc/os-release")
    if rel.exists():
        for row in rel.read_text(encoding="utf-8", errors="ignore").splitlines():
            if row.startswith("PRETTY_NAME="):
                line("发行版", row.split("=", 1)[1].strip())

    found = None
    if Path(WQY_TTC).exists():
        good = font_renders_cjk(WQY_TTC)
        line("wqy-zenhei", WQY_TTC, "OK" if good else "FAIL")
        if good:
            found = WQY_TTC
    else:
        line("wqy-zenhei", f"{WQY_TTC} 不存在", "FAIL")

    if found is None:
        line("fonts-wqy-zenhei", "未安装或不可用", "FAIL")
        if shutil.which("fc-match"):
            try:
                m = subprocess.run(["fc-match", "-f", "%{file}", ":lang=zh"],
                                   capture_output=True, text=True, timeout=10)
                cand = m.stdout.strip()
                if cand and Path(cand).exists() and font_renders_cjk(cand):
                    line("fc-match :lang=zh 兜底", cand, "OK")
                    found = cand
                    print("      注意：不是 wqy-zenhei，字形/粗细与预期可能不同，务必肉眼确认。")
                else:
                    line("fc-match :lang=zh 兜底", cand or "(空)", "FAIL")
            except Exception as exc:
                line("fc-match", f"调用失败 {exc!r}", "WARN")
    if found is None:
        print("      装法（需你批准，本脚本不装）：sudo apt install fonts-wqy-zenhei")
        print("      或直接跑项目脚本：sudo bash 电控/deploy/install.sh")
        ok = False
    return found


def check_pillow() -> None:
    global ok
    head("5/5  Pillow（显示的唯一第三方依赖）")
    venv = first_existing(VENV_PYTHONS)
    if venv:
        try:
            out = subprocess.run([venv, "-c", "import PIL;print(PIL.__version__)"],
                                 capture_output=True, text=True, timeout=30)
            v = (out.stdout or out.stderr).strip()
            line("链路 venv", f"{venv} -> {v}",
                 "OK" if out.returncode == 0 else "FAIL")
            if out.returncode != 0:
                print("      修：cd 电控/deploy && .venv/bin/pip install -r requirements.txt")
                ok = False
        except Exception as exc:
            line("链路 venv", f"{venv} 执行失败 {exc!r}", "WARN")
    else:
        line("链路 venv", "未找到 .venv —— install.sh 可能还没跑过", "WARN")
        print("      链路的解释器必须是这个 venv；用系统 python3 跑 run_chain 会缺依赖。")

    try:
        import PIL
        line("当前解释器 Pillow", PIL.__version__, "OK")
    except ImportError:
        line("当前解释器 Pillow", "未安装（若是 venv 解释器则必须修）", "FAIL")
        ok = False
        return
    try:
        from PIL import ImageFont
        ImageFont.load_default(size=20)
        line("load_default(size=)", "支持（>= 10.1）", "OK")
    except TypeError:
        line("load_default(size=)", "不支持（< 10.1）", "WARN")


def check_names() -> str | None:
    global ok
    head("2/5  货物名称表（--names-file）")
    path = first_existing(NAMES_CANDIDATES)
    if not path:
        line("名称表", f"{' / '.join(NAMES_CANDIDATES)} 都不存在", "FAIL")
        print("      从开发机推：scp 工具/generated_names.json pi@<host>:/opt/ec-chain/names.json")
        ok = False
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        names = {int(k): str(v) for k, v in data.items()}
    except Exception as exc:
        line(path, f"解析失败 {exc!r}", "FAIL")
        ok = False
        return None
    missing = [c for c in CLASS_IDS if c not in names]
    line("文件", path, "OK" if not missing else "FAIL")
    for c in sorted(names):
        print(f"         {c} -> {names[c]}")
    if missing:
        line("缺 class_id", missing, "FAIL")
        print("      run_chain 会 fail-closed（build_display_view 抛 ValueError），"
              "该件不显示 = 超 15 秒本轮结束。已在主机复现过这个报错。")
        ok = False
    return path


def check_images() -> str | None:
    global ok
    head("3/5  货物图片目录（--image-dir）")
    d = first_existing(IMAGE_DIR_CANDIDATES)
    if not d:
        line("图片目录", f"{' / '.join(IMAGE_DIR_CANDIDATES)} 都不存在", "FAIL")
        print("      仓库里目前没有任何可用的货物图片（见部署清单 §3）——这是本任务最大的空白。")
        ok = False
        return None
    dd = Path(d)
    have, missing = [], []
    for cid in CLASS_IDS:
        hit = next((dd / f"{cid}{e}" for e in EXTS if (dd / f"{cid}{e}").is_file()), None)
        (have if hit else missing).append(f"{cid}={hit.name}" if hit else str(cid))
    line("目录", d, "OK" if not missing else "FAIL")
    line("找到", ", ".join(have) or "(无)", "OK" if have else "FAIL")
    if missing:
        line("缺 image_id", ", ".join(missing), "FAIL")
        print("      命名规则：<image_id>.png/.jpg/.jpeg/.webp/.bmp，image_id == class_id（冻结 1:1）。")
        print("      缺图时 HdmiDisplayRenderer 抛 ImageLoadError（fail-closed），该件不上屏。")
        ok = False
    return d if not missing else None


def check_frame_output() -> None:
    global ok
    head("4/5  帧输出（--frame-output）")
    if not Path("/dev/fb0").exists():
        line("/dev/fb0", "不存在", "FAIL")
        print("      ⚠️ auto 会静默降级成 none：不报错、不告警、屏幕什么都不显示。")
        print("         赛题：15 秒没显示本次分拣信息 = 本轮比赛结束。这是最危险的失败方式。")
        print("      查：lsmod | grep -E 'vc4|v3d'")
        print("          grep -iE 'fb|dtoverlay' /boot/firmware/config.txt /boot/config.txt")
        print("      修（改系统配置，需你批准）：config.txt 加 dtoverlay=vc4-kms-v3d 后确认 /dev/fb0 出现")
        ok = False
        return
    line("/dev/fb0", "存在", "OK")
    bpp_p, vsize_p = Path("/sys/class/graphics/fb0/bits_per_pixel"), Path("/sys/class/graphics/fb0/virtual_size")
    bpp = bpp_p.read_text().strip() if bpp_p.exists() else "?"
    vsize = vsize_p.read_text().strip() if vsize_p.exists() else "?"
    line("virtual_size", vsize, "OK" if vsize == "1024,600" else "WARN")
    if bpp == "32":
        line("bits_per_pixel", "32（RGB888 直写正确）", "OK")
        print("      启动命令用：--frame-output fb0")
    else:
        line("bits_per_pixel", f"{bpp}（run_chain 直写 RGB888 -> 画面是花的）", "FAIL")
        print("      ⚠️ build_frame_output 只写 RGB888 原始字节，非 32bpp 时必须改代码（要你批准）。")
        print("      先别上 fb0；用 --frame-output file 验证内容，bpp 适配另开一条。")
        ok = False
    if not os.access("/dev/fb0", os.W_OK):
        line("写权限", "当前用户不可写（需在 video 组或 root）", "WARN")


def main() -> int:
    print("树莓派屏幕部署自检（只读；不装包、不改配置）")
    font = check_font()
    names = check_names()
    images = check_images()
    check_frame_output()
    check_pillow()

    head("可复制的启动命令" if ok else "启动命令（有 FAIL 项，先修）")
    for row in (
        "cd /opt/ec-chain/deploy && ./.venv/bin/python run_chain.py \\",
        "  --port /dev/ttyAMA0 --baud 115200 \\",
        "  --round-id <本轮ID> --round-task-id <本轮任务号> \\",
        "  --config /home/pi/sorting_config.ini \\",
        f'  --font "{font or WQY_TTC}" \\',
        f'  --names-file "{names or NAMES_CANDIDATES[0]}" \\',
        f'  --image-dir "{images or IMAGE_DIR_CANDIDATES[0]}" \\',
        "  --start-round \\",
        "  --frame-output fb0 -v",
    ):
        print(row)
    print()
    print("  --start-round 会先要求输入 HOME；板子无绝对位置，仍须操作员现场确认，")
    print("  去掉它则链路停在 RECOVERY_LOCK，什么都不会派发、屏幕也不会动。")
    print()
    print("结论：" + ("5 项齐备，可以按上面命令启动。" if ok else "有 FAIL 项 —— 按上面提示逐条修，别急着启动。"))
    print("提醒：本脚本只读环境，不等于屏幕实机验证 —— 还要肉眼确认中文不是方块、图片显示出来了。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
