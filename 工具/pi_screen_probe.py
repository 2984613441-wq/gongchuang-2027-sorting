#!/usr/bin/env python3
"""不经 run_chain，直接把一帧合成画面点亮到 /dev/fb0（树莓派单文件工具）。

为什么存在：run_chain.py 真实模式有 8 道 fail-closed 门，其中 [DropPoints] 六盒落点
和 --image-dir 目录两道今晚过不去，启动就 SystemExit，屏幕根本跑不到。本脚本只做
"屏幕"这一件事：复用 HdmiDisplayRenderer 合成假数据帧 -> 写 /dev/fb0 + 另存 PNG，
并把该看的自检项逐条打出来。

不做的事：不碰串口、不碰落点表、不改 run_chain、不改 DisplayViewModel 字段、不改
DISPLAY_CONTENT 线格式、不装包。跑本脚本不等于链路通过，只等于"屏幕这一环"通过。

用法（树莓派上，用链路同一个解释器最准）：
    /opt/ec-chain/deploy/.venv/bin/python pi_screen_probe.py
    /opt/ec-chain/deploy/.venv/bin/python pi_screen_probe.py --image-dir /opt/ec-chain/images
    /opt/ec-chain/deploy/.venv/bin/python pi_screen_probe.py --image-dir ./images --all-images
主机上（没有 /dev/fb0）只验排版与中文字形：
    python pi_screen_probe.py --no-fb0 --image-dir docs/货物图片-第一赛段 --all-images
或从开发机推过去跑：
    ssh pi@<host> 'python3 - --no-fb0' < 工具/pi_screen_probe.py
"""
from __future__ import annotations

import argparse
import errno
import os
import sys
import tempfile
from pathlib import Path

WQY_TTC = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
FONT_CANDIDATES = (
    WQY_TTC,
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    # 下面几个只为让 --no-fb0 主机排版权检能跑（Windows 开发机）。
    # 树莓派上这些路径不存在，Path.is_file() 会直接跳过，不改变树莓派行为。
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
)
# 与 display_hdmi.py 的 _BACKGROUND 一致：用它判断"这一帧是不是真的画上了东西"
BG = (14, 22, 40)
NAME_BOX = (600, 186, 1010, 250)  # 右栏"货物名称"文字区域（display_hdmi 布局）
SCREEN_W, SCREEN_H = 1024, 600
EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

failures: list[str] = []


def reconfigure_stdout() -> None:
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
    if verdict == "FAIL":
        failures.append(f"{label}: {value}")


# ---------------------------------------------------------------------------
# electrical_control 的导入（树莓派上由 install.sh 写进 venv 的 .pth；主机上兜底加 path）
# ---------------------------------------------------------------------------
def import_display_stack():
    here = Path(__file__).resolve().parent
    candidates = [
        os.environ.get("EC_SRC", ""),
        str(here.parent / "电控" / "src"),   # 仓库内：工具/ 的兄弟目录
        "/opt/ec-chain/src",                  # 树莓派部署约定
        str(here),                            # 与 run_chain.py 同目录放下时
    ]
    try:
        from electrical_control.rpi import ItemTaskContext  # noqa: F401
    except ImportError:
        for cand in candidates:
            if cand and Path(cand).is_dir():
                sys.path.insert(0, cand)
                try:
                    from electrical_control.rpi import ItemTaskContext  # noqa: F401
                    break
                except ImportError:
                    sys.path.pop(0)
        else:
            raise
    from electrical_control.protocol.item_context import ItemTaskPayload
    from electrical_control.rpi import ItemTaskContext
    from electrical_control.rpi.display import DisplayViewModel
    from electrical_control.rpi.display_hdmi import HdmiDisplayRenderer

    return HdmiDisplayRenderer, DisplayViewModel, ItemTaskContext, ItemTaskPayload


# ---------------------------------------------------------------------------
# 字体：找不到中文字体就明确报错，绝不静默渲染成方块
# ---------------------------------------------------------------------------
def font_renders_cjk(font_path: str) -> bool:
    """渲染两个不同汉字比位图；位图相同 = 缺字形（方块）。镜像 control_panel.font_renders_cjk。"""
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype(font_path, 48)
    except Exception:
        return False

    def glyph(ch: str) -> bytes:
        img = Image.new("L", (96, 96), 0)
        ImageDraw.Draw(img).text((0, 0), ch, font=font, fill=255)
        return img.tobytes()

    return glyph("五") != glyph("棱")


def resolve_font(explicit: str | None) -> str | None:
    head("1/5  中文字体（font_path）")
    print("      说明：display_hdmi.py 的 font_path=None 会用 PIL 内置字体，中文一律画成方块。")
    print("            所以本脚本拒绝在无中文字体的情况下出图。")
    if explicit:
        line("--font", explicit, "OK" if Path(explicit).is_file() else "FAIL")
        if not Path(explicit).is_file():
            return None
        if font_renders_cjk(explicit):
            line("字形自检（五 vs 棱）", "位图不同 = 真的画得出中文", "OK")
            return explicit
        line("字形自检（五 vs 棱）", "位图相同 = 该字体缺 CJK 字形，上屏全是方块", "FAIL")
        return None

    for cand in FONT_CANDIDATES:
        if not Path(cand).is_file():
            continue
        if font_renders_cjk(cand):
            line("中文字体", cand, "OK")
            if cand != WQY_TTC:
                print("      注意：不是 wqy-zenhei，字形/粗细与预期可能不同，务必肉眼确认。")
            return cand
        line("字体候选", f"{cand}（缺 CJK 字形）", "WARN")
    line("中文字体", f"{' / '.join(FONT_CANDIDATES)} 都不可用", "FAIL")
    print("      装法（需你执行，本脚本不装）：sudo apt install fonts-wqy-zenhei")
    print("      或跑项目脚本：sudo bash 电控/deploy/install.sh")
    return None


# ---------------------------------------------------------------------------
# 图片：<image_id>.png/.jpg/...，与 run_chain.build_image_loader 同规则
# ---------------------------------------------------------------------------
def make_image_loader(image_dir: str | None):
    from PIL import Image

    if not image_dir:
        print()
        line("货物图片", "--image-dir 未给：用纯色占位块代替（版面可验，图片内容不可验）", "WARN")

        def placeholder(image_id: int):
            return Image.new("RGB", (400, 400), (40 + image_id * 37 % 200, 90, 140))

        return placeholder

    directory = Path(image_dir)

    def from_dir(image_id: int):
        for ext in EXTS:
            candidate = directory / f"{image_id}{ext}"
            if candidate.is_file():
                return Image.open(candidate)
        present = sorted(p.name for p in directory.iterdir() if p.is_file())[:12]
        raise FileNotFoundError(
            f"image_id={image_id} 在 {image_dir} 下未找到（需 <image_id>.png/.jpg）；"
            f"目录里现有：{present or '(空)'}"
        )

    return from_dir


# ---------------------------------------------------------------------------
# fb0
# ---------------------------------------------------------------------------
def fb0_facts(fb_path: str) -> dict:
    base = Path("/sys/class/graphics") / Path(fb_path).name

    def read(name: str) -> str | None:
        p = base / name
        try:
            return p.read_text().strip()
        except OSError:
            return None

    return {
        "exists": Path(fb_path).exists(),
        "bpp": read("bits_per_pixel"),
        "virtual_size": read("virtual_size"),
        "stride": read("stride"),
        "writable": os.access(fb_path, os.W_OK),
    }


def open_fb0(fb_path: str):
    """打开 /dev/fb0，失败时把原因说清楚（设备不存在 / 权限 / 被占用）。"""
    try:
        return open(fb_path, "r+b", buffering=0), None
    except FileNotFoundError:
        return None, (
            "设备不存在：内核没有 framebuffer 设备。\n"
            "  查：lsmod | grep -E 'vc4|v3d'；grep -iE 'fb|dtoverlay' /boot/firmware/config.txt /boot/config.txt\n"
            "  修（改系统配置，需你执行）：config.txt 加 dtoverlay=vc4-kms-v3d 与 hdmi_force_hotplug=1 后重启，再确认 /dev/fb0 出现"
        )
    except PermissionError:
        return None, (
            "权限不足：当前用户打不开（非 root 且不在 video 组）。\n"
            "  查：ls -l /dev/fb0；id\n"
            "  修（需你执行）：sudo usermod -aG video $USER 后重新登录，或本次用 sudo 跑本脚本"
        )
    except OSError as exc:
        if exc.errno == errno.EBUSY:
            return None, (
                "被占用：/dev/fb0 已被其它进程打开（fbi / 控制台 / 另一个写屏进程）。\n"
                "  查：sudo fuser -v /dev/fb0 或 ls -l /proc/*/fd 2>/dev/null | grep fb0\n"
                "  修：停掉占用进程（如系统控制台 getty/display manager），再重试"
            )
        if exc.errno == errno.EACCES:
            return None, f"权限被拒（EACCES）：{exc}"
        return None, f"打开失败 OSError(errno={exc.errno}): {exc}"


def packed_bytes(frame, bpp: int, stride: int | None) -> bytes:
    """帧 -> 待写字节。仅支持 32bpp RGB888 直写；stride 有行padding时补零避免整幅斜切。"""
    raw = frame.tobytes()  # RGB888
    row = frame.width * 4
    if bpp != 32 or not stride or stride <= row:
        return raw
    pad = b"\x00" * (stride - row)
    return b"".join(raw[y * row:(y + 1) * row] + pad for y in range(frame.height))


# ---------------------------------------------------------------------------
# 合成
# ---------------------------------------------------------------------------
def make_payload(payload_cls, *, target_seq: int, class_id: int, image_id: int):
    """按 dataclass 字段动态构造 ItemTaskPayload。

    ponytail: ITEM_TASK 载荷在演进（V0.8 = 8 字节，V0.9 = 12 字节加 pick_x/pick_y），
    写死字段名会让探针在协议一动就崩。未知的必填字段 -> 明确报错，不猜。
    """
    import dataclasses

    known = {
        "target_seq": target_seq,
        "class_id": class_id,      # 名称已在本地解析；class_id 只为重建 DisplayContent/CRC
        "image_id": image_id,      # 探针里让 image_id 直接等于要显示的图片编号（1..6）
        "grip_angle": 0xFF,        # 爪不旋转（冻结值）
    }
    values = {}
    for field in dataclasses.fields(payload_cls):
        if field.name in known:
            values[field.name] = known[field.name]
        elif field.name.startswith("pick_") or field.name in ("x_position", "y_position", "z_position"):
            values[field.name] = 0  # 抓取点/落点：探针不关心，只要能让载荷合法构造
        elif field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING:
            continue
        else:
            raise TypeError(
                f"探针不认识 ItemTaskPayload 的新必填字段 {field.name!r}：协议改了，请同步本脚本"
            )
    return payload_cls(**values)


def compose(renderer_cls, view, ctx_cls, payload_cls, image_loader, font_path, image_id: int):
    """用真实 HdmiDisplayRenderer 合成一帧，返回 (frame, content_crc32)。"""
    task = ctx_cls(
        round_id="probe",
        task_id=1,
        frame_seq=1,
        payload=make_payload(payload_cls, target_seq=view.target_seq, class_id=0, image_id=image_id),
    )
    captured: list = []
    renderer = renderer_cls(
        width=SCREEN_W,
        height=SCREEN_H,
        image_loader=image_loader,
        frame_output=captured.append,
        font_path=font_path,
        task=task,
    )
    pending = renderer.present(view)          # 图片缺失会在这里 fail-closed 抛 ImageLoadError
    receipt = pending.complete()              # 走一遍回执路径，确认 DisplayContent/CRC 能重建
    if len(captured) != 1:
        raise RuntimeError("frame_output 没被调用 / 被调用多次，合成没有产出")
    return captured[0], receipt.content_crc32


def frame_has_text(frame) -> bool:
    """右栏名称区域是否真的有非背景像素（防"全黑但脚本说成功"）。"""
    crop = frame.crop(NAME_BOX)
    return any(px != BG for px in crop.getdata())


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description="不经 run_chain，直接把合成帧点亮到 /dev/fb0 并做屏幕自检",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--fb", default="/dev/fb0", help="framebuffer 设备（默认 /dev/fb0）")
    ap.add_argument("--no-fb0", action="store_true", help="不碰 framebuffer，只合成 PNG（主机可用）")
    ap.add_argument("--png", default=None, help="PNG 保存路径（默认 <临时目录>/pi_screen_probe.png）")
    ap.add_argument("--image-dir", default=None, help="货物图片目录，按 <image_id>.png/.jpg 命名")
    ap.add_argument("--font", default=None, help="中文字体路径（默认自动找 wqy-zenhei）")
    ap.add_argument("--name", default="青色正方体", help="右栏显示的货物名称（假数据）")
    ap.add_argument("--target-seq", type=int, default=3, help="序号（假数据）")
    ap.add_argument("--success-count", type=int, default=5, help="分拣成功总数量（假数据）")
    ap.add_argument("--result-code", type=int, default=0, help="结果码：0=SUCCESS，其它=FAILURE")
    ap.add_argument("--image-id", type=int, default=1, help="要显示的图片编号（默认 1）")
    ap.add_argument("--all-images", action="store_true",
                    help="依次渲染 image_id 1..6 各一帧（验 6 张货物图能不能都上屏）")
    ap.add_argument("--write-anyway", action="store_true",
                    help="bpp 不是 32 时也强写 fb0（默认跳过：非 32bpp 直写 RGB888 画面是花的）")
    args = ap.parse_args()

    print("树莓派屏幕点亮探针（不碰串口/落点表/run_chain；不装包）")

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        head("0/5  Pillow")
        line("Pillow", "未安装 —— 合成本身就做不了", "FAIL")
        print("      修（需你执行）：/opt/ec-chain/deploy/.venv/bin/pip install -r 电控/deploy/requirements.txt")
        return 2

    try:
        renderer_cls, view_cls, ctx_cls, payload_cls = import_display_stack()
    except ImportError as exc:
        head("0/5  electrical_control 导入")
        line("import electrical_control", f"失败 {exc!r}", "FAIL")
        print("      修：用链路的 venv 解释器跑（install.sh 已把 电控/src 写进它的 .pth）：")
        print("          /opt/ec-chain/deploy/.venv/bin/python pi_screen_probe.py")
        print("      或设 EC_SRC 指向 电控/src：EC_SRC=/opt/ec-chain/src python3 pi_screen_probe.py")
        return 2

    out_dir = Path(args.png).parent if args.png else Path(tempfile.gettempdir())
    png_base = Path(args.png) if args.png else out_dir / "pi_screen_probe.png"

    font_path = resolve_font(args.font)
    if font_path is None:
        print("\n结论：中文字体不可用 —— 拒绝出图（静默画成方块 = 现场看不出错的失败）。")
        return 2

    image_loader = make_image_loader(args.image_dir)
    view = view_cls(
        target_seq=args.target_seq,
        name=args.name,
        image_id=args.image_id,
        success_count=args.success_count,
        result_code=args.result_code,
    )

    ids = list(range(1, 7)) if args.all_images else [args.image_id]

    head("2/5  合成帧（HdmiDisplayRenderer 真实代码路径）")
    frames = {}
    for image_id in ids:
        # view.image_id 与 payload.image_id 必须一致：renderer 用 payload 重建 DisplayContent
        this_view = view_cls(
            target_seq=view.target_seq,
            name=view.name,
            image_id=image_id,
            success_count=view.success_count,
            result_code=view.result_code,
        )
        try:
            frame, crc = compose(renderer_cls, this_view, ctx_cls, payload_cls,
                                 image_loader, font_path, image_id)
        except Exception as exc:
            line(f"image_id={image_id} 合成", f"{type(exc).__name__}: {exc}", "FAIL")
            if args.image_dir:
                print("      这是 fail-closed：图缺了就不上屏。检查 --image-dir 里的 <image_id>.png/.jpg。")
            continue
        frames[image_id] = frame
        png = png_base.with_name(f"{png_base.stem}_{image_id}{png_base.suffix}") if args.all_images else png_base
        if not png.suffix:
            # --png 不带扩展名时 PIL 推断不出格式，save() 会抛 KeyError: ''（实测于 2026-09-17）
            png = png.with_suffix(".png")
        frame.save(png)
        line(f"image_id={image_id} 合成", f"{frame.size[0]}x{frame.size[1]} {frame.mode} -> {png}", "OK")
        line(f"image_id={image_id} 右侧名称区有内容", frame_has_text(frame), "OK" if frame_has_text(frame) else "FAIL")
        line(f"image_id={image_id} DisplayContent CRC32", f"0x{crc:08X}", "OK")
    if not frames:
        print("\n结论：一帧都没合成出来 —— 屏幕无从谈起。先修上面的 FAIL。")
        return 1
    print(f"      提示：把 PNG 拉回来看肉眼效果（scp pi@<host>:{png_base.parent}/*.png .）")

    head("3/5  /dev/fb0 设备与格式")
    facts = fb0_facts(args.fb)
    # --no-fb0 是"只合成"模式：主机上本来就没有 /dev/fb0，不该记成 FAIL
    line(f"{args.fb} 存在", facts["exists"],
         "OK" if facts["exists"] else ("WARN" if args.no_fb0 else "FAIL"))
    line("bits_per_pixel", facts["bpp"] or "读不到", "OK" if facts["bpp"] == "32" else "WARN")
    line("virtual_size", facts["virtual_size"] or "读不到",
         "OK" if facts["virtual_size"] == f"{SCREEN_W},{SCREEN_H}" else "WARN")
    line("stride", facts["stride"] or "读不到（按 width*4 处理）", "")
    line("当前用户可写", facts["writable"], "OK" if facts["writable"] else "WARN")

    fb_bytes = None
    if not facts["exists"]:
        print("      /dev/fb0 不存在 -> 跳过写入。没有这个设备，run_chain --frame-output fb0 会直接 SystemExit。")
    elif facts["bpp"] != "32":
        print(f"      ⚠️ bpp={facts['bpp']} ≠ 32：run_chain.build_frame_output 只写 RGB888 原始字节，")
        print("         非 32bpp 直接写屏画面是花的（README「当前限制」第 5 条）。")
        print("         先别用 --frame-output fb0；bpp 适配是另一条要你批准的改动。")
        if not args.write_anyway:
            print("         （本脚本默认跳过写入；确实想看到花屏效果再加 --write-anyway）")
    elif facts["virtual_size"] and facts["virtual_size"] != f"{SCREEN_W},{SCREEN_H}":
        print(f"      ⚠️ 屏分辨率 {facts['virtual_size']} ≠ {SCREEN_W}x{SCREEN_H}：")
        print("         display_hdmi 的版面是按 1024x600 硬编码的，别的分辨率会错位/被裁。")

    verify_ok = None
    if not args.no_fb0 and facts["exists"] and (facts["bpp"] == "32" or args.write_anyway):
        head("4/5  写入 /dev/fb0")
        fh, reason = open_fb0(args.fb)
        if fh is None:
            line("打开 " + args.fb, reason, "FAIL")
        else:
            stride = int(facts["stride"]) if facts["stride"] else None
            try:
                for image_id, frame in frames.items():
                    data = packed_bytes(frame, 32, stride)
                    fh.seek(0)
                    fh.write(data)
                    line(f"写帧 image_id={image_id}",
                         f"{len(data)} 字节（{frame.size[0]}x{frame.size[1]} RGB888）", "OK")
                    if verify_ok is None:  # 回读校验：write 没报错 ≠ 真写对了
                        try:
                            fh.seek(0)
                            back = fh.read(min(len(data), 65536))
                            verify_ok = back == data[:len(back)]
                            line("回读校验（前 64KB 逐字节比对）",
                                 "一致" if verify_ok else "不一致 = 没真写进去",
                                 "OK" if verify_ok else "FAIL")
                        except OSError as exc:
                            line("回读校验", f"跳过（设备不可读 {exc!r}）—— 只证明 write 没报错", "WARN")
            except OSError as exc:
                line("写帧", f"失败 {exc!r}", "FAIL")
            finally:
                fh.close()
    else:
        head("4/5  写入 /dev/fb0")
        line("写入", "已跳过" if not args.no_fb0 else "--no-fb0：只合成 PNG", "WARN")

    head("5/5  肉眼判据（脚本判不了，必须你看屏）")
    print("      [ ] 屏上是不是出现了这一帧（不是全黑、不是花屏、不是白屏）")
    print("      [ ] 中文是不是方块：'第 3 件' / '货物名称' / '分拣成功总数量' 都能认出字形")
    print("      [ ] 左栏有没有货物图片（不是空框、不是整块纯色）")
    print("      [ ] 右边名称、SUCCESS、数字与假数据一致（%s / SUCCESS / %d）" % (args.name, args.success_count))
    print("      [ ] 屏边缘有没有被裁（1024x600 全屏，无黑边/无拉伸）")

    head("结论")
    if args.no_fb0:
        print("只验了合成 + 中文字形 + PNG。" + ("合成全部 OK。" if not failures else "有 FAIL 项。"))
        print("这一步在主机上也能跑 —— 不能当成实机屏幕通过。")
    elif verify_ok and not failures:
        print("屏幕这一环：合成 OK、/dev/fb0 写入并回读一致。")
        print("仍然要你肉眼确认上面 5 条；脚本证明不了'人看着对'。")
    else:
        print("有 FAIL/WARN 项 —— 按上面逐条修。屏幕没点亮之前，run_chain 的显示闭环没有意义。")
    if failures:
        print("\nFAIL 汇总：")
        for f in failures:
            print("  - " + f.replace("\n", "\n    "))
    print("\n提醒：本脚本不碰串口/落点表，跑通它 ≠ run_chain 能启动（六盒落点 + 图片目录两道门还是要修）。")
    return 0 if (not failures and (args.no_fb0 or verify_ok)) else 1


if __name__ == "__main__":
    reconfigure_stdout()
    raise SystemExit(main())
