# -*- coding: utf-8 -*-
"""诊断：动机构前后，画面到底变了什么？（只读，不改任何生产文件）

要回答两个问题：
  1. 变化是**均匀铺满**整幅，还是集中在某几条带里？（8×8 网格密度）
  2. 能不能用**一次纯平移**解释掉？（相位相关 + 平移后残留）
     · 平移后残留≈0  ⇒ 整幅画面被整体搬走了 ⇒ 相机跟着机构动（或视场整体平移）
     · 平移后残留仍然大 ⇒ 有一个大结构在固定背景前移过
"""
import glob
import os
import sys

import cv2
import numpy as np

OUT = os.environ.get("FORENSIC_DIR", "/root/forensic")
THRESH = 25
G = 8   # 网格 8x8


def main():
    a = cv2.imread(os.path.join(OUT, "_maskcal_A.png"), cv2.IMREAD_GRAYSCALE)
    if a is None:
        print("读不到 _maskcal_A.png")
        return 1
    h, w = a.shape
    print("A=%s  阈值 %d" % (a.shape, THRESH))
    print("网格每格 = %dx%d px，数字 = 该格内变化像素百分比" % (w // G, h // G))
    bs = sorted(glob.glob(os.path.join(OUT, "_maskcal_B*.png")))
    for p in bs:
        b = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        if b is None or b.shape != a.shape:
            print("跳过 %s" % p)
            continue
        d = (cv2.absdiff(a, b) > THRESH).astype(np.uint8)
        grid = d.reshape(G, h // G, G, w // G).mean(axis=(1, 3))
        print("\n=== %s   总变化 %.1f%% ===" % (os.path.basename(p), d.mean() * 100))
        for r in range(G):
            print("   " + " ".join("%4d" % round(grid[r, c] * 100) for c in range(G)))

        # 相位相关：最佳整数/亚像素平移
        (dx, dy), resp = cv2.phaseCorrelate(np.float32(a), np.float32(b))
        M = np.float32([[1, 0, dx], [0, 1, dy]])
        bs_shift = cv2.warpAffine(b, M, (w, h), borderMode=cv2.BORDER_REPLICATE)
        d2 = (cv2.absdiff(a, bs_shift) > THRESH)
        print("   最佳整体平移 dx=%+.1f dy=%+.1f  resp=%.3f   ⇒ 平移后残留变化 %.1f%%"
              % (dx, dy, resp, d2.mean() * 100))

        # 可视化：A 转彩色，变化像素刷红
        vis = cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)
        vis[d > 0] = (0, 0, 255)
        outp = os.path.join(OUT, "_maskcal_diag_%s.png"
                            % os.path.basename(p).replace("_maskcal_B_", "").replace(".png", ""))
        cv2.imwrite(outp, vis)
        print("   可视化已存 %s（灰=没变，红=变了）" % outp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
