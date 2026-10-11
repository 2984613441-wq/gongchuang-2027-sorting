# -*- coding: utf-8 -*-
"""第三轮视觉补丁：M2 绝对尺寸下限 + M3 饱和门 + M5 black 静置3帧 + AE/AWB 开关。

依据：外部 AI 三任务报告（2026-09-21）的实测量化结论。
断言式：任一处不"恰好命中一次"⇒ 整体中止，不写任何文件。
用法: py -3 工具/apply_vision_patch3.py [--apply]
"""
import io, os, shutil, sys, time, py_compile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V6 = os.path.join(ROOT, "视觉", "src", "maixcam_deploy", "stage1_color_v6_send.py")
R = []

# ── 常量区 ──────────────────────────────────────────────────────────────
R.append((
 '_REJ_TOT = {}                  # F3(2026-09-21) 进程内累计，用于事件触发打印\n',
 '_REJ_TOT = {}                  # F3(2026-09-21) 进程内累计，用于事件触发打印\n'
 '\n'
 '# M2/M3/M5(2026-09-21)：外部报告实测量化后新增的三道门 + black 更严确认。\n'
 '# M2 绝对尺寸下限（det 口径；= 320 口径短边 62px / 面积 2600px²）：\n'
 '#   实测依据：关掉 c2 后每帧多出的假目标短边 59px@320、面积 2258~2485px²@320，\n'
 '#   而最小真件是短边 73px / 面积 3089px²。且过曝把件切成两半时残片 area=1550px²@320、\n'
 '#   extent=0.5047（≈理想三角 0.5）⇒ **相对形状判据抓不到，只有绝对面积下限能抓**。\n'
 '#   ⚠️ 只加下限，坚决不加上限（实测 cube 的 cyan 候选 99×94 / 8078.6px² 已超出旧"自述带"）。\n'
 'MIN_BBOX_SIDE_DET = 43         # 短边下限 px(224)\n'
 'MIN_AREA_DET_PX = 1274.0       # 面积下限 px²(224)\n'
 '# M3 饱和门：本场景正常帧的 (V>=245 & S<=25) 像素实测为 0 / 0 / 0。\n'
 '#   门限 1500px@320 落在"被 c4 打掉(1793)"与"坐标还能用(1257)"之间。\n'
 'MAX_SATURATED_PX = 1500\n'
 '# M5 black 更严确认：夹爪/机架也是黑的，黑件要求连续 3 帧静置才确认（彩色仍 2 帧）。\n'
 'BLACK_CONFIRM_FRAMES = 3\n'
 '# AE/AWB 锁定开关：**默认关**。锁定后六色 HSV 阈值必须全部重标，故先留开关、现场取证后再开。\n'
 'LOCK_AE_AWB = False\n',
 'M2/M3/M5/AE 常量'))

# ── 计数键补 c7 ─────────────────────────────────────────────────────────
R.append((
 '                c4_color_frac=0, c5_black_core=0, c6_black_mutex=0)\n',
 '                c4_color_frac=0, c5_black_core=0, c6_black_mutex=0,\n'
 '                c7_min_size=0, c8_saturated=0)\n',
 '计数键 c7/c8'))

# ── M3 饱和门（hsv 之后、进入颜色循环之前）───────────────────────────────
R.append((
 '    min_area = MIN_AREA_FRACTION * width * height\n'
 '    max_area = MAX_AREA_FRACTION * width * height\n',
 '    min_area = MIN_AREA_FRACTION * width * height\n'
 '    max_area = MAX_AREA_FRACTION * width * height\n'
 '    # M3(2026-09-21) 饱和门：过曝会让 S→0，六个彩窗**同时**失配 ⇒ 整件消失；\n'
 '    # 更阴险的是"把掩膜切成两半、全闸放行、抓取点偏 8.7mm"（实测 prism_tri r=20）。\n'
 '    # 本场景正常帧的 (V>=245 & S<=25) 像素实测为 0/0/0，故这道门几乎零误伤。\n'
 '    _sat = int(np.count_nonzero((hsv[:, :, 2] >= 245) & (hsv[:, :, 1] <= 25)))\n'
 '    if _sat >= MAX_SATURATED_PX:\n'
 '        _REJ["c8_saturated"] = _sat\n'
 '        for _k in _REJ:\n'
 '            _REJ_TOT[_k] = _REJ_TOT.get(_k, 0) + _REJ[_k]\n'
 '        print("V6 SATURATED frame=%d sat=%d -> 本帧不报目标" % (\n'
 '            getattr(analyze, "_frames", 0) + 1, _sat))\n'
 '        analyze._frames = getattr(analyze, "_frames", 0) + 1\n'
 '        return [], (round(x0 * sx), round(y0 * sy), round(x1 * sx), round(y1 * sy))\n',
 'M3 饱和门'))

# ── M2 绝对尺寸下限（c2 之后、c3 之前）──────────────────────────────────
R.append((
 '            if min(w, h) / max(w, h) < 0.28 or area / (w*h) < 0.35:\n',
 '            # M2(2026-09-21) 绝对尺寸下限：c2 之后、c3 之前。\n'
 '            # 它同时是"贴 ROI 边的静物黑块"的兜底与"过曝半件"的唯一解药\n'
 '            # （半件 extent≈0.5 与理想三角无异，只有绝对面积能识别）。\n'
 '            if min(w, h) < MIN_BBOX_SIDE_DET or area < MIN_AREA_DET_PX:\n'
 '                _REJ["c7_min_size"] += 1\n'
 '                continue\n'
 '            if min(w, h) / max(w, h) < 0.28 or area / (w*h) < 0.35:\n',
 'M2 绝对尺寸下限'))

# ── M5 black 静置 3 帧 ──────────────────────────────────────────────────
R.append((
 '            previous["confirmed"] = previous["confirmed"] or previous["hits"] >= CONFIRM_FRAMES\n',
 '            # M5(2026-09-21)：黑色要求连续 3 帧静置（夹爪/机架也是黑的，需要更强证据）。\n'
 '            _need = BLACK_CONFIRM_FRAMES if color == "black" else CONFIRM_FRAMES\n'
 '            previous["confirmed"] = previous["confirmed"] or previous["hits"] >= _need\n',
 'M5 black 3 帧'))

# ── AE/AWB 锁定（默认关）────────────────────────────────────────────────
R.append((
 '    cam = camera.Camera(FRAME_SIZE, FRAME_SIZE, image.Format.FMT_RGB888)\n',
 '    cam = camera.Camera(FRAME_SIZE, FRAME_SIZE, image.Format.FMT_RGB888)\n'
 '    # AE/AWB 锁定（2026-09-21，API 真名已在设备上实测确认，MaixPy 4.12.5）：\n'
 '    #   camera.AeMode/AwbMode members = [Invalid, Auto, Manual]\n'
 '    #   Camera.exposure(us) / gain / iso / luma(0..100) / exp_mode(AeMode) [deprecated]\n'
 '    #   Camera.set_wb_gain(List[float])  ← 文档原话"disable auto white balance"\n'
 '    # 默认关（LOCK_AE_AWB=False）：**锁定后六色 HSV 阈值必须全部重标**，\n'
 '    # 必须先在现场正常光照下读一次基线值再写死。\n'
 '    try:\n'
 '        _wb = list(cam.set_wb_gain())\n'
 '        print("V6 AE/AWB baseline: exp_mode=%s exposure=%s gain=%s iso=%s luma=%s wb_gain=%s"\n'
 '              % (cam.exp_mode(), cam.exposure(), cam.gain(), cam.iso(), cam.luma(), _wb))\n'
 '        if LOCK_AE_AWB:\n'
 '            cam.exp_mode(camera.AeMode.Manual)\n'
 '            cam.awb_mode(camera.AwbMode.Manual)\n'
 '            if _wb:\n'
 '                cam.set_wb_gain(_wb)\n'
 '            print("V6 AE/AWB LOCKED: exposure=%s gain=%s wb_gain=%s"\n'
 '                  % (cam.exposure(), cam.gain(), cam.set_wb_gain()))\n'
 '    except Exception as _exc:\n'
 '        print("V6 AE/AWB lock unavailable: %s（继续用自动曝光）" % _exc)\n',
 'AE/AWB 基线+锁定'))


def main():
    apply = "--apply" in sys.argv
    s = io.open(V6, encoding="utf-8").read()
    bad = 0
    for old, new, tag in R:
        n = s.count(old)
        print("%-22s hit %d %s" % (tag, n, "" if n == 1 else "  <<< MUST BE 1"))
        if n != 1:
            bad += 1
    if bad:
        print("\nFAIL: %d spot(s) -> ABORT, nothing written." % bad)
        return 1
    if not apply:
        print("\nDRY-RUN OK (%d spots). add --apply." % len(R))
        return 0
    shutil.copy2(V6, V6 + ".bak-visionpatch3-" + time.strftime("%Y%m%d-%H%M%S"))
    for old, new, tag in R:
        s = s.replace(old, new, 1)
    io.open(V6, "w", encoding="utf-8", newline="").write(s)
    py_compile.compile(V6, doraise=True)
    print("APPLIED %d spots + py_compile OK" % len(R))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
