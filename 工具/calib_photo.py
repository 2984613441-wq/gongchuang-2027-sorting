#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从【一张照片】生成像素→毫米标定（尺子 + 夹爪停在中心）。

你只需要：拍一张照片，里面有①夹爪尖端（停在机器坐标 0,0）②一把尺子，
然后在这个程序里点 3 下鼠标。

━━━ 原理（为什么一张照片就够）━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  尺子   → 给【比例】：每像素多少毫米
  夹爪   → 给【原点】：机器坐标 (0,0) 落在哪个像素
  尺子的方向 → 给【机器 +X 轴在画面上朝哪】
  机器 +Y 轴 = 把 +X 轴在画面上【逆时针转 90°】
               （相机是从上往下看的正视图，不会镜像，所以右手定则成立）

  于是 6 个仿射参数全部确定：
      x_mm = a11*u + a12*v + tx
      y_mm = a21*u + a22*v + ty

━━━ 前置要求（很简单，但不满足会算错）━━━━━━━━━━━━━━━━━━━━━━━
  1. 尺子要【平行于机器的 X 轴】摆（不用管尺子的 0 在哪，只用到刻度差）
  2. 尺子和夹爪要在【同一张照片】里，而且都在相机看得见的范围内
  3. 相机不能歪着装（倾斜 < 几度就行；这个程序假设相机是垂直向下看的）
  4. 照片最好直接用 MaixCAM 拍（它出的是 320x320）。
     用别的相机拍也行，程序会自动按目标分辨率折算，但**视野必须和被换算的一致**。

━━━ 用法 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    py -3 工具/calib_photo.py 照片.jpg
    py -3 工具/calib_photo.py 照片.jpg --flip-y       # 若验证发现 Y 方向反了
    py -3 工具/calib_photo.py --selftest              # 只跑数学自检

  点完会打印能直接粘进 电控/calibration_config.ini 的 6 行，
  并在照片上画出【算出来的原点与坐标轴】供你肉眼确认。
"""

from __future__ import annotations

import math
import sys

# MaixCAM 实际输出帧（视觉链路里 (u,v) 就是这个尺寸下的像素）
MAIX_FRAME = (320, 320)


# ===========================================================================
# 纯计算部分（无 GUI，可单独自检）
# ===========================================================================
def compute_affine(origin, tick_a, tick_b, mm_a, mm_b, *,
                   photo_size, frame_size=MAIX_FRAME, flip_y=False):
    """由 3 个点算 6 个仿射参数。

    Args:
        origin: 夹爪尖端在【照片】上的像素 (u,v)，机器坐标 = (0,0)
        tick_a / tick_b: 尺子上两个刻度在【照片】上的像素
        mm_a / mm_b: 这两个刻度的尺子读数（单位 mm）
        photo_size: 照片的 (宽, 高)，用于折算到 MaixCAM 帧
        frame_size: 视觉链路实际输出帧，默认 320x320
        flip_y: 若机器 +Y 在画面上是顺时针 90°（左手系），置 True

    Returns:
        (params, info)：params 是 6 个参数的 dict，info 含中间量与校验信息。
    """

    def to_frame(p):
        return (p[0] * frame_size[0] / photo_size[0],
                p[1] * frame_size[1] / photo_size[1])

    o = to_frame(origin)
    a = to_frame(tick_a)
    b = to_frame(tick_b)

    du, dv = b[0] - a[0], b[1] - a[1]
    length = math.hypot(du, dv)
    if length < 1e-6:
        raise ValueError("尺子上点的两个刻度是同一个像素，请点开一点")
    delta_mm = mm_b - mm_a
    if abs(delta_mm) < 1e-9:
        raise ValueError("两个刻度的读数相同，无法定比例")

    mm_per_px = abs(delta_mm) / length

    # 机器 +X 在像素空间的单位向量。
    # 若读数从 A 到 B 是【增加】的，说明画面从 A 到 B 的方向就是机器 +X；否则反过来。
    sign = 1.0 if delta_mm > 0 else -1.0
    ex = (sign * du / length, sign * dv / length)

    # 机器 +Y = +X 在画面上逆时针转 90°。
    # 屏幕坐标 y 朝下，视觉上的逆时针 (x,y) -> (y,-x)。
    ey = (ex[1], -ex[0])
    if flip_y:
        ey = (-ey[0], -ey[1])

    # 推导：像素位移 p = x_mm·(px/mm)·ex + y_mm·(px/mm)·ey
    #   → p·ex = x_mm·(px/mm)   → x_mm = (p·ex)·mm_per_px
    # 所以系数是【乘 mm_per_px】，不是除。（自检用例抓到的正是这个反了。）
    a11, a12 = mm_per_px * ex[0], mm_per_px * ex[1]
    a21, a22 = mm_per_px * ey[0], mm_per_px * ey[1]
    tx = -(a11 * o[0] + a12 * o[1])
    ty = -(a21 * o[0] + a22 * o[1])

    params = {"a11": a11, "a12": a12, "tx": tx,
              "a21": a21, "a22": a22, "ty": ty}
    info = {
        "mm_per_px": mm_per_px,
        "px_per_mm": 1.0 / mm_per_px,
        "origin_frame": o,
        "ex": ex,
        "ey": ey,
        "rotation_deg": math.degrees(math.atan2(ex[1], ex[0])),
        "frame_scale": (frame_size[0] / photo_size[0], frame_size[1] / photo_size[1]),
    }
    return params, info


def apply_affine(params, u, v):
    """用算出来的 6 个参数把像素换成毫米（验证用）。"""
    return (params["a11"] * u + params["a12"] * v + params["tx"],
            params["a21"] * u + params["a22"] * v + params["ty"])


def _selftest() -> int:
    """构造已知真值 → 反推几个像素点 → 检查能不能还原。"""

    frame = (320, 320)
    photo = (320, 320)
    # 真值：机器 +X 沿画面 +u，+Y 沿画面 -v，2 像素/mm，原点在 (160,160)
    #   x_mm = (u-160)/2      y_mm = -(v-160)/2
    # 取尺子沿 +u 方向放，读数 10mm 在 u=100，40mm 在 u=160（30mm = 60px → 2px/mm）
    params, info = compute_affine(
        origin=(160, 160), tick_a=(100, 200), tick_b=(160, 200),
        mm_a=10.0, mm_b=40.0, photo_size=photo, frame_size=frame,
    )
    assert abs(info["px_per_mm"] - 2.0) < 1e-9, info["px_per_mm"]

    checks = [((160, 160), (0.0, 0.0)),
              ((260, 160), (50.0, 0.0)),
              ((160, 60), (0.0, 50.0)),
              ((200, 120), (20.0, 20.0))]
    for (u, v), (want_x, want_y) in checks:
        got_x, got_y = apply_affine(params, u, v)
        assert abs(got_x - want_x) < 1e-9, (u, v, got_x, want_x)
        assert abs(got_y - want_y) < 1e-9, (u, v, got_y, want_y)

    # 尺子方向反着点（读数递减）也要得出同一个结果
    params2, _ = compute_affine(
        origin=(160, 160), tick_a=(160, 200), tick_b=(100, 200),
        mm_a=40.0, mm_b=10.0, photo_size=photo, frame_size=frame,
    )
    for key in params:
        assert abs(params[key] - params2[key]) < 1e-9, key

    # 照片不是 320 时要按比例折算：把上面所有点乘 4（1280x1280 照片）
    params3, info3 = compute_affine(
        origin=(640, 640), tick_a=(400, 800), tick_b=(640, 800),
        mm_a=10.0, mm_b=40.0, photo_size=(1280, 1280), frame_size=frame,
    )
    assert abs(info3["px_per_mm"] - 2.0) < 1e-9, info3["px_per_mm"]
    for key in params:
        assert abs(params[key] - params3[key]) < 1e-7, (key, params[key], params3[key])

    # flip_y 必须真的翻
    params4, _ = compute_affine(
        origin=(160, 160), tick_a=(100, 200), tick_b=(160, 200),
        mm_a=10.0, mm_b=40.0, photo_size=photo, frame_size=frame, flip_y=True,
    )
    assert abs(params4["a21"] + params["a21"]) < 1e-9
    assert abs(params4["a22"] + params["a22"]) < 1e-9

    print("calib_photo 数学自检通过：比例/原点/方向/折算/翻转 全部正确")
    return 0


# ===========================================================================
# GUI 部分
# ===========================================================================
STEPS = (
    ("origin", "① 点【夹爪尖端】\n\n（夹爪现在是停在机器坐标 0,0 的）"),
    ("tick_a", "② 点尺子上的【第一个刻度】\n\n（随便挑一个看得清的刻度）"),
    ("tick_b", "③ 点尺子上的【第二个刻度】\n\n（离第一个远一点，越远越准）"),
)


def run_gui(path: str, flip_y: bool) -> int:
    import tkinter as tk
    from tkinter import simpledialog

    try:
        from PIL import Image, ImageDraw, ImageTk
    except ImportError:
        print("需要 Pillow：py -3 -m pip install pillow")
        return 2

    image = Image.open(path).convert("RGB")
    photo_w, photo_h = image.size

    root = tk.Tk()
    root.title("标定：点 3 下")
    max_w, max_h = 1100, 750
    scale = min(1.0, max_w / photo_w, max_h / photo_h)
    disp_w, disp_h = max(1, int(photo_w * scale)), max(1, int(photo_h * scale))

    canvas = tk.Canvas(root, width=disp_w, height=disp_h, highlightthickness=0)
    canvas.pack()
    tk_img = ImageTk.PhotoImage(image.resize((disp_w, disp_h), Image.LANCZOS))
    canvas.create_image(0, 0, anchor="nw", image=tk_img)
    label = tk.Label(root, text="", font=("Microsoft YaHei", 13), justify="left")
    label.pack(fill="x")

    state: dict = {"index": 0, "points": {}, "marks": []}

    def show(text):
        label.config(text=text)

    def mark(u, v, text):
        du, dv = u * scale, v * scale
        canvas.create_line(du - 14, dv, du + 14, dv, fill="#ff3355", width=2)
        canvas.create_line(du, dv - 14, du, dv + 14, fill="#ff3355", width=2)
        canvas.create_text(du + 18, dv - 14, text=text, anchor="w",
                           fill="#ffdd55", font=("Microsoft YaHei", 12, "bold"))
        state["marks"].append((du, dv))

    def finish():
        pts = state["points"]
        mm_a = simpledialog.askfloat("刻度读数", "② 那个刻度的尺子读数是多少 mm？",
                                     parent=root)
        if mm_a is None:
            root.destroy()
            return
        mm_b = simpledialog.askfloat("刻度读数", "③ 那个刻度的尺子读数是多少 mm？",
                                     parent=root)
        if mm_b is None:
            root.destroy()
            return
        try:
            params, info = compute_affine(
                pts["origin"], pts["tick_a"], pts["tick_b"], mm_a, mm_b,
                photo_size=(photo_w, photo_h), flip_y=flip_y,
            )
        except ValueError as exc:
            show(f"❌ {exc}\n\n关掉重开，重新点一次。")
            return

        report = format_report(params, info, path, (photo_w, photo_h), flip_y)
        print(report)

        # 把算出来的原点与坐标轴画回去，肉眼确认
        overlay = image.copy()
        draw = ImageDraw.Draw(overlay)
        ou, ov = info["origin_frame"]
        for direction, color, text in ((info["ex"], "#00e0ff", "+X"),
                                       (info["ey"], "#ffb000", "+Y")):
            for length_mm in (30, 60, 90):
                end_u = ou + direction[0] * length_mm * info["px_per_mm"]
                end_v = ov + direction[1] * length_mm * info["px_per_mm"]
                draw.line((ou, ov, end_u, end_v), fill=color, width=3)
                draw.text((end_u, end_v), f"{text} {length_mm}mm", fill=color)
        draw.ellipse((ou - 6, ov - 6, ou + 6, ov + 6), outline="#ff3355", width=4)
        out_path = path.rsplit(".", 1)[0] + "_标定示意.png"
        overlay.save(out_path)

        canvas.create_image(0, 0, anchor="nw", image=ImageTk.PhotoImage(
            overlay.resize((disp_w, disp_h), Image.LANCZOS)))
        show(f"✅ 算完了。已在照片上画出原点(红圈)与 +X/+Y 轴方向。\n"
             f"示意图存到：{out_path}\n"
             f"比例 {info['px_per_mm']:.3f} px/mm（1 像素 ≈ "
             f"{info['mm_per_px']:.2f}mm）   命令行窗口里有 6 行参数")

    def on_click(event):
        if state["index"] >= len(STEPS):
            return
        key, _ = STEPS[state["index"]]
        u, v = event.x / scale, event.y / scale
        state["points"][key] = (u, v)
        mark(u, v, ["夹爪(0,0)", "刻度A", "刻度B"][state["index"]])
        state["index"] += 1
        if state["index"] < len(STEPS):
            show(STEPS[state["index"]][1])
        else:
            show("三个点都点好了，正在问刻度读数…（看弹出的输入框）")
            root.after(120, finish)

    canvas.bind("<Button-1>", on_click)
    show(STEPS[0][1] + f"\n\n照片 {photo_w}x{photo_h}"
         + ("，Y 轴已设为翻转" if flip_y else ""))
    root.mainloop()
    return 0


def format_report(params, info, path, photo_size, flip_y) -> str:
    lines = [
        "",
        "=" * 66,
        f"照片：{path}  {photo_size[0]}x{photo_size[1]}"
        f"  →  折算到 MaixCAM {MAIX_FRAME[0]}x{MAIX_FRAME[1]}"
        f"（缩放 {info['frame_scale'][0]:.4f}, {info['frame_scale'][1]:.4f}）",
        f"比例：{info['px_per_mm']:.3f} 像素/mm    1 像素 ≈ {info['mm_per_px']:.2f} mm",
        f"夹爪(0,0) 落在像素 ({info['origin_frame'][0]:.1f}, {info['origin_frame'][1]:.1f})",
        f"画面里 +X 轴朝向：{info['rotation_deg']:.1f}°（0° = 朝右；"
        f"{'Y 已翻转' if flip_y else 'Y 未翻转'}）",
        "=" * 66,
        "",
        "# ---- 粘进 电控/calibration_config.ini 的 [CameraCalibration] ----",
    ]
    for key in ("a11", "a12", "tx", "a21", "a22", "ty"):
        lines.append(f"{key} = {params[key]:.6f}")
    lines += [
        "",
        "camera_height 保持已经实测的 262.0 不用改（除非托盘换过）。",
        "",
        "⚠️ 粘完必须验证一次：把物体放在工作台某处，看程序算出的预测位置，",
        "   让夹爪走过去。若【Y 方向反了】→ 加 --flip-y 重跑这个程序；",
        "   若【X 方向反了】→ 说明照片里尺子是反着点的，把两个读数对调重跑。",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return _selftest()
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    return run_gui(args[0], "--flip-y" in argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
