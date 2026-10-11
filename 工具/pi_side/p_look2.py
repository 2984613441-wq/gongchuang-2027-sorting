# -*- coding: utf-8 -*-
"""只读监听 8765：解出全部可见物块的 像素 -> 装置 -> 滑台 坐标。
⚠️ pixel_to_device 返回的是 0.1mm（mm10），必须 /10 之后再加 ToolOffset(mm)。"""
import socket, sys, time
import configparser
sys.path.insert(0, "/home/pi/电控/src")
from electrical_control.rpi.vision_ingest import parse_batch_targets
from electrical_control.rpi.pixel_to_device import PixelToDeviceConverter

_CFG = "/home/pi/电控/calibration_config.ini"
conv = PixelToDeviceConverter(_CFG)
# 🔴 2026-09-21 修：这里原本写死 TO = (-120.5, -43.5)，而配置文件早已改成 y=-52.5
#    ⇒ 打印出来的"滑台取料点"Y 方向偏 9mm。用这个偏值去走，再目视量偏移，
#    量到的 9mm 会被误当成"夹爪又偏了"⇒ 二次修正 ToolOffset。**必须只有一份真相。**
_cp = configparser.ConfigParser()
_cp.read(_CFG, encoding="utf-8")
TO = (float(_cp.get("ToolOffset", "x_mm")), float(_cp.get("ToolOffset", "y_mm")))
# 工作区限值也读同一份（滑台系）——判据必须和链一模一样，不许有第二份
WX = (_cp.getfloat("WorkspaceLimits", "x_min"), _cp.getfloat("WorkspaceLimits", "x_max"))
WY = (_cp.getfloat("WorkspaceLimits", "y_min"), _cp.getfloat("WorkspaceLimits", "y_max"))
print("[p_look2] ToolOffset 读自 %s = (%.1f, %.1f) mm" % (_CFG, TO[0], TO[1]))
print("[p_look2] 工作区(滑台系) = x[%.1f,%.1f] y[%.1f,%.1f]" % (WX + WY))
NAMES = {1:"青-正方体",2:"绿-正方体",3:"红-三棱柱",4:"蓝-三棱柱",5:"黑-圆柱",6:"橙-圆柱"}

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("0.0.0.0", 8765)); srv.listen(4); srv.settimeout(2.0)
print("监听 8765（最多 8 秒）……\n")
t0 = time.time(); shown = 0
while time.time() - t0 < 8.0 and shown == 0:
    try:
        conn, _ = srv.accept()
    except socket.timeout:
        continue
    conn.settimeout(2.0)
    data = b""
    while len(data) < 300:
        try: ch = conn.recv(300 - len(data))
        except socket.timeout: break
        if not ch: break
        data += ch
        if len(data) >= 3 and len(data) >= 3 + 7*data[0]: break
    conn.close()
    if len(data) < 3: continue
    b = parse_batch_targets(data)
    print("task_id=%s  count=%d" % (b.task_id, len(b.targets)))
    for t in b.targets:
        # 🔴 2026-09-21 修：原来用默认 check_workspace=True，等于拿【装置坐标】去比
        #    【滑台系】的 [WorkspaceLimits]（pixel_to_device.py:332-333 自己写明：
        #    运动链要先叠加 ToolOffset、再检查最终 PICK，所以链传 False）。
        #    后果是判定全反：装置 x=102.4 的件滑台点其实 = -18.1 在范围内（链**会**抓），
        #    却被报成"越界"；而滑台 x=-96.8 的件机械够不到，却一声不响。
        #    现在与链同口径：先叠加 ToolOffset，再比滑台工作区。
        dev = conv.pixel_to_device(t.pixel_x, t.pixel_y, t.box_id, check_workspace=False)
        print("  box_id=%d (%s)  px=%d py=%d" % (t.box_id, NAMES.get(t.box_id,"?"), t.pixel_x, t.pixel_y))
        if dev is None:
            print("      ❌ 像素域外 / 缺 [ObjectHeights] —— 这件取不到")
            continue
        dx_mm, dy_mm = dev[0]/10.0, dev[1]/10.0          # ★ mm10 -> mm
        sx_mm, sy_mm = dx_mm + TO[0], dy_mm + TO[1]
        print("      装置 = (%.1f, %.1f) mm" % (dx_mm, dy_mm))
        if not (WX[0] <= sx_mm <= WX[1] and WY[0] <= sy_mm <= WY[1]):
            print("      ❌ 滑台取料点 = (%.1f, %.1f) mm **超出工作区** "
                  "[%.1f,%.1f]x[%.1f,%.1f] ⇒ 这件链不会抓（机械够不到）"
                  % (sx_mm, sy_mm, WX[0], WX[1], WY[0], WY[1]))
            continue
        print("      ★滑台取料点 = (%.1f, %.1f) mm  ✅ 在可达区内" % (sx_mm, sy_mm))
    shown = 1
srv.close()