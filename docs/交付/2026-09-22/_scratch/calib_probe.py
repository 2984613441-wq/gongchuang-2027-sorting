a11,a12,tx = -0.027890, -0.477932, 145.697
a21,a22,ty = -0.477932,  0.027890,  39.782
TOx,TOy = -108.5, -20.5
WX = (-95.0, 85.0); WY = (-97.5, 87.5)   # Pi 工作区（= 最终下发 PICK 的坐标系）

def dev(u,v): return (a11*u+a12*v+tx, a21*u+a22*v+ty)
def pick(u,v):
    x,y = dev(u,v); return (x+TOx, y+TOy)

import math
scale = math.hypot(a11,a12)
print(f"比例 = {scale:.4f} mm/px   旋转 = {math.degrees(math.atan2(a12,a11)):.2f} deg")
print(f"共形? a21==a12 -> {a21==a12} ; a22==-a11 -> {abs(a22+a11)<1e-9}")
print()
print("=== 画面四角 -> 装置坐标 / 最终 PICK ===")
for (u,v) in [(0,0),(320,0),(0,320),(320,320)]:
    d = dev(u,v); p = pick(u,v)
    print(f"  (u={u:3d},v={v:3d})  装置=({d[0]:7.1f},{d[1]:7.1f})   PICK=({p[0]:7.1f},{p[1]:7.1f})")
print()
print("=== 画面里【够不到】的像素区域（PICK 越出工作区） ===")
bad=0; tot=0
for u in range(0,320,10):
    for v in range(0,320,10):
        tot+=1
        x,y = pick(u,v)
        if not (WX[0]<=x<=WX[1] and WY[0]<=y<=WY[1]): bad+=1
print(f"  抽样 {tot} 点中 {bad} 点越界  => 约 {100*bad/tot:.0f}% 的画面是【看得见抓不到】")
print()
print("=== 两条边界分别卡在哪个像素 ===")
# x 边界: PICK_x >= -95  <=> 装置x >= 13.5
for v in (0,80,160,240,300):
    # 求 u 使 PICK_y = -97.5  (y 下界)
    u_edge = (ty + TOy + 97.5 + a22*v)/(-a21)
    print(f"  v={v:3d}: PICK_y 触到 y_min 的 u ≈ {u_edge:.0f}  (>此值的图像右侧够不到)")
for u in (0,100,200,300):
    v_edge = (tx + TOx + 95.0 + a11*u)/(-a12)   # PICK_x >= -95
    print(f"  u={u:3d}: PICK_x 触到 x_min 的 v ≈ {v_edge:.0f}  (>此值的图像下缘够不到)")
