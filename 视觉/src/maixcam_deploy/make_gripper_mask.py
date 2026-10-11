# -*- coding: utf-8 -*-
"""④-②(2026-09-21) 标定「机构扫掠遮罩」—— 只读相机，**绝不动机构**（移动由外部命令做）。

为什么需要它
------------
夹爪和 X/Y 轴的黑色方框**本身就是黑的**，跟黑圆柱同色。实测三张不同件的实拍互相比：
    · 件 bbox 内帧间变化 36.9% ~ 67.3%
    · 那两块固定黑物内变化 0.00% ~ 0.06%
⇒ 颜色 / 亮度 / 形状 / 面积**全都分不开**，唯一与光照无关的判据是「动过没有」。

而且现在挡住幻影的余量很薄：短边 59px vs M2 下限 62px、面积 2470 vs 2600（余 4.6%），
幻影自身的帧间抖动却有 ±10% ⇒ 换个光照它就会通过 M2 变成一个"看起来完全像件"的目标。
这张遮罩把余量从 4.6% 换成结构性的。

⚠️ 一条必须记住的坑（我第一版写错过）
--------------------------------------
**不要"回到原位置再抓 B 帧"。** 步进电机走等量反向步会精确回到原位置，两帧画面一模一样，
差分恒等于 0 ⇒ 遮罩必然是空的。实测噪声地板就是 **0.0000%**（A vs A2 只有 0.2s，
一个像素差都没超过 25 灰阶）。所以 **B 帧必须在"已经移开的位置"抓**，
而且沿路径**多点抓**才覆盖得住中间位置。

三步用法（移动由外部命令做，本脚本只抓帧/算差分）
--------------------------------------------------
    ssh root@172.20.10.9
    cd /root/forensic

    # ① 机构停在 HOME、画面里没有人手 → 抓 A 与 A2（顺带量噪声地板）
    python make_gripper_mask.py a

    # ② 每走到一个新位置就抓一帧（tag 随便取，多个 B 帧会取并集）
    #    ← 位置之间的移动由你/外部命令做，本脚本不管
    python make_gripper_mask.py c s1
    python make_gripper_mask.py c s2
    ...

    # ③ 算差分、存遮罩（**不需要相机**，随时可跑）
    python make_gripper_mask.py b

产出 `/root/forensic/gripper_mask.png`（白 = 机构扫掠区，已外扩）。
生产侧只在**这个文件存在时**才启用 c9 门；不存在就是零行为变化。

判读
----
脚本会打「信号/噪声」。比值 < `MIN_SIGNAL_RATIO` 说明那一帧没拍出机构位移
（或自动曝光漂了）⇒ 遮罩不可信，重做。

⚠️ 相机是独占设备：跑 a / c 之前必须先停掉 V6（b 不需要相机）。
⚠️ 全程用**与生产同一套**相机参数（320×320 RGB888、自动曝光）。刻意**不锁 AE** ——
   生产跑的就是自动曝光，锁了反而量到另一个亮度下的遮罩。
⚠️ 遮罩与取景绑定：**相机一挪，遮罩作废，必须重标**。
"""
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2                                                     # noqa: E402
import numpy as np                                             # noqa: E402
from maix import camera, image                                 # noqa: E402

REQ_FRAME_SIZE = 320      # 与生产 FRAME_SIZE 一致
WARMUP_FRAMES = 30        # 先丢 30 帧等自动曝光稳定
DIFF_THRESH = 25          # 灰度差阈值
DILATE_PX = 5             # 外扩像素（保守方向：遮罩宁可大一点）
MIN_SIGNAL_RATIO = 10.0   # 信号/噪声 下限
OPEN_KERNEL = np.ones((3, 3), np.uint8)

OUT_DIR = os.environ.get("FORENSIC_DIR", "/root/forensic")
A_PATH = os.path.join(OUT_DIR, "_maskcal_A.png")
A2_PATH = os.path.join(OUT_DIR, "_maskcal_A2.png")
B_GLOB = os.path.join(OUT_DIR, "_maskcal_B*.png")
MASK_PATH = os.path.join(OUT_DIR, "gripper_mask.png")


def grab(cam, n):
    """丢 warmup 后连抓 n 张灰度图（每张间隔 0.2s）。"""
    for _ in range(WARMUP_FRAMES):
        cam.read()
    outs = []
    for _ in range(n):
        frame = None
        for _ in range(100):
            frame = cam.read()
            if frame is not None:
                break
        if frame is None:
            raise SystemExit("读不到帧：相机被别的进程占着？先把 V6 停掉。")
        rgb = image.image2cv(frame, ensure_bgr=False, copy=False)
        outs.append(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY))      # cvtColor 会新分配
        time.sleep(0.2)
    return outs


def changed_fraction(a, b, thresh=DIFF_THRESH):
    return float(np.count_nonzero(cv2.absdiff(a, b) > thresh)) / float(a.size)


def _open_camera():
    return camera.Camera(REQ_FRAME_SIZE, REQ_FRAME_SIZE,
                         image.Format.FMT_RGB888)


def stage_a():
    cam = _open_camera()
    try:
        g1, g2 = grab(cam, 2)
    finally:
        cam.close()
    cv2.imwrite(A_PATH, g1)
    cv2.imwrite(A2_PATH, g2)
    noise = changed_fraction(g1, g2)
    print("A  已存 %s" % A_PATH)
    print("A2 已存 %s" % A2_PATH)
    print("噪声地板（机构没动、相隔约 0.2s 的两帧）：变化像素 %.4f%%" % (noise * 100))
    print("")
    print("→ 接下来：每走到一个新位置就抓一帧，例如")
    print("     python make_gripper_mask.py c s1")
    print("   ⚠️ **不要先回原位置再抓** —— 回去了两帧就一样了，差分恒为 0。")
    print("   ⚠️ 抓之前确保画面里没有人手、托盘上的件没被动过。")
    return 0


def stage_c(tag):
    if not os.path.exists(A_PATH):
        raise SystemExit("缺 %s —— 先跑 `python make_gripper_mask.py a`" % A_PATH)
    cam = _open_camera()
    try:
        (g,) = grab(cam, 1)
    finally:
        cam.close()
    p = os.path.join(OUT_DIR, "_maskcal_B_%s.png" % tag)
    cv2.imwrite(p, g)
    a = cv2.imread(A_PATH, cv2.IMREAD_GRAYSCALE)
    sig = changed_fraction(a, g) if a is not None else float("nan")
    print("B[%s] 已存 %s   相对 A 的变化像素 %.4f%%" % (tag, p, sig * 100))
    if sig < 0.001:
        print("   ⚠️ 几乎没有变化 —— 机构是不是没动？这一帧对遮罩没有贡献。")
    return 0


def stage_b():
    need = [A_PATH, A2_PATH]
    for p in need:
        if not os.path.exists(p):
            raise SystemExit("缺 %s —— 先跑 `python make_gripper_mask.py a`" % p)
    bs = sorted(glob.glob(B_GLOB))
    if not bs:
        raise SystemExit("没有 B 帧（%s）—— 先跑 `python make_gripper_mask.py c <tag>`"
                         % B_GLOB)
    a = cv2.imread(A_PATH, cv2.IMREAD_GRAYSCALE)
    a2 = cv2.imread(A2_PATH, cv2.IMREAD_GRAYSCALE)
    noise = changed_fraction(a, a2)
    ratio_worst = float("inf")
    union = np.zeros(a.shape, np.uint8)
    print("A=%s  噪声地板 %.4f%%   阈值 %d   外扩 %dpx"
          % (os.path.basename(A_PATH), noise * 100, DIFF_THRESH, DILATE_PX))
    for p in bs:
        b = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        if b is None or b.shape != a.shape:
            print("  跳过 %s（读不了或尺寸不符）" % os.path.basename(p))
            continue
        raw = cv2.absdiff(a, b)
        sig = changed_fraction(a, b)
        ratio = (sig / noise) if noise > 0 else float("inf")
        ratio_worst = min(ratio_worst, ratio)
        union = cv2.bitwise_or(union, ((raw > DIFF_THRESH).astype(np.uint8)) * 255)
        print("  %-24s 信号 %.4f%%   信号/噪声 %.1f" % (os.path.basename(p),
                                                        sig * 100, ratio))
        time.sleep(0)
    print("最差信号/噪声 = %.1f （下限 %.1f）" % (ratio_worst, MIN_SIGNAL_RATIO))
    if ratio_worst < MIN_SIGNAL_RATIO:
        print("")
        print("❌ 有帧的信号太弱 ⇒ 那一帧机构没到位，或自动曝光在两次抓帧之间漂了。")
        print("   遮罩不可信，**不要用**。重做：每走一段就抓一帧，走完再算 b。")
        return 1

    swept = cv2.morphologyEx(union, cv2.MORPH_OPEN, OPEN_KERNEL)   # 去掉孤立噪点
    k = 2 * DILATE_PX + 1
    swept = cv2.dilate(swept, np.ones((k, k), np.uint8))
    n = int(cv2.countNonZero(swept))
    ys, xs = np.nonzero(swept)
    if n == 0 or len(ys) == 0:
        print("❌ 遮罩是空的 —— 没有任何像素被判为「动过」。重做。")
        return 1
    if n > 0.5 * swept.size:
        print("❌ 遮罩覆盖 %.1f%% 画面（%d/%d）⇒ 多半是曝光漂了或整幅都变，"
              "不是机构扫掠。重做。" % (100.0 * n / swept.size, n, swept.size))
        return 1

    cv2.imwrite(MASK_PATH, swept)
    print("")
    print("✅ 遮罩已存 %s" % MASK_PATH)
    print("   白像素 %d (%.2f%%)   bbox=(x=%d y=%d w=%d h=%d)"
          % (n, 100.0 * n / swept.size, int(xs.min()), int(ys.min()),
             int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)))
    print("→ 生产侧与取证脚本下次启动会自动载入它（analyze(gripper_mask=...)）。")
    print("⚠️ 相机一挪，这张遮罩作废，必须重标。")
    return 0


def main(argv):
    if len(argv) < 2 or argv[1] not in ("a", "b", "c"):
        print(__doc__)
        return 2
    os.makedirs(OUT_DIR, exist_ok=True)
    if argv[1] == "a":
        return stage_a()
    if argv[1] == "b":
        return stage_b()
    if len(argv) != 3:
        print("用法：python make_gripper_mask.py c <tag>")
        return 2
    return stage_c(argv[2])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
