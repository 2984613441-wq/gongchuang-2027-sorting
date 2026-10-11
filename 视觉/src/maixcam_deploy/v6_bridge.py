"""V6 视觉 → 树莓派 TCP 发送桥（2026-09-18）

【为什么需要这个】
朋友的 V6（stage1_color_v6_stable.py）只在屏幕上画框，**不发送任何数据**。
她自己的交接说明 :32 写着「V6 当前只做视觉显示和日志，不向树莓派/舵机发送运动指令」。
所以她做完了「识别」，但「把结果传出去」这一环从来没做过。

【怎么用（3 步）】
1. 把本文件整个复制到 V6 那个单文件的**最上面**（import 之后、常量之前）。
2. 在 V6 的 main() 里、`tracker = StableTargets()` 后面加一行：
       sender = BatchSender()
3. 在 V6 的 main() 循环里、`results = tracker.update(...)` **后面**加一行：
       sender.send(results)

就这样。V6 的识别逻辑一个字都不用改（那是朋友的，她确认过稳定）。

【线上格式（已冻结，不要改）】
BATCH_TARGETS：
    target_count(1) + task_id(2,BE) + target[N]
每个 target 7 字节：
    id_byte(1) + confidence(1, 0-100) + X(2,BE) + Y(2,BE) + angle(1, 0xFF)

**id_byte 在校赛模式下填 box_id(1..6)**（用户 2026-09-17 批准，见
docs/交接台账-2026-09-17.md §2.1）。V6 的 `bin` 字段就是货格号，直接用。

【三个必须遵守的约束】
1. `bin is None`（HOLD 灰框）**必须丢掉**，绝不能当货格发。
2. `task_id` **不能是 0** —— 树莓派 task_id 对不上就整批丢。
   默认走 TASK_ID 常量；跟不上轮次时至少要 >0。
3. V6 是 **320×320** 像素，而标定按 448×448 算的。
   本桥**原样透传像素坐标**（不缩放），口径统一由树莓派侧负责 ——
   见文件末尾的「待办」。
"""

import json
import socket
import struct
import time

# ── 配置（按现场改这三个）──────────────────────────────────────────
GATEWAY_HOST = "172.20.10.8"   # 树莓派
GATEWAY_PORT = 8765
TASK_ID = 1                    # ⚠️ 绝不能是 0（见约束 2）
ENABLE_NETWORK = True          # False = 只打印不发，用于单独调视觉

# 发送节流：V6 最高 6 FPS，不需要每帧都发
MIN_SEND_INTERVAL_S = 0.10

ANGLE_NONE = 0xFF
TARGET_BYTES = 7


def encode_target(row):
    """把一个 V6 result 编成 7 字节。认不出货格（bin=None）返回 None。

    row 是 stage1_color_v6_stable.py 里 analyze() 的产物，字段：
        bin(1..6 或 None) / bbox=(left,top,w,h) / color_fraction / color / shape
    """
    bin_id = row.get("bin")
    if bin_id is None:
        # HOLD 灰框 / 未知颜色 —— 不输出货格，也不发这一件
        return None
    if not isinstance(bin_id, int) or not (1 <= bin_id <= 6):
        return None

    left, top, w, h = row["bbox"]
    cx, cy = row.get("center") or (int(left + w / 2), int(top + h / 2))
    if not (0 <= cx <= 0xFFFF and 0 <= cy <= 0xFFFF):
        return None

    # confidence：V6 没有 score，只有 color_fraction。这是【合成值】，
    # 不是模型置信度。写在这里是为了让下游有个 0-100 的数可显示。
    frac = row.get("color_fraction") or 0.0
    conf = max(0, min(100, int(round(frac * 100))))

    return struct.pack(">BBHHB", bin_id, conf, cx, cy, ANGLE_NONE)


def encode_batch_targets(rows, task_id):
    """把若干 V6 result 编成完整的 BATCH_TARGETS 数据区。

    rows 里 bin=None 的会被丢掉。全都认不出时 target_count=0（这是合法的空帧）。
    """
    if not isinstance(task_id, int) or not (0 <= task_id <= 0xFFFF):
        raise ValueError("task_id 必须落在 0..65535")
    if task_id == 0:
        # 不抛错，但必须让人看见 —— 树莓派 task_id 对不上会整批丢
        print("[V6-BRIDGE] WARNING: task_id=0，树莓派可能整批丢弃")

    payload = bytearray()
    for row in rows:
        packed = encode_target(row)
        if packed is not None:
            if len(packed) != TARGET_BYTES:
                raise AssertionError("target 必须正好 7 字节")
            payload += packed

    count = len(payload) // TARGET_BYTES
    if count > 255:
        raise ValueError("target_count 是 1 字节，不能超过 255")
    return bytes([count]) + struct.pack(">H", task_id) + bytes(payload)


class BatchSender:
    """带重连的 TCP 发送器。收不到货格时不发（省流量、也避免空帧刷屏）。"""

    def __init__(self, host=GATEWAY_HOST, port=GATEWAY_PORT, task_id=TASK_ID,
                 enable=ENABLE_NETWORK, interval=MIN_SEND_INTERVAL_S):
        self._host = host
        self._port = port
        self._task_id = task_id
        self._enable = enable
        self._interval = interval
        self._sock = None
        self._last = 0.0
        self.sent_frames = 0
        self.sent_items = 0
        self.skipped_frames = 0

    # ── 连接管理 ────────────────────────────────────────────────
    def _ensure(self):
        if self._sock is not None:
            return True
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect((self._host, self._port))
            s.settimeout(None)
            self._sock = s
            print("[V6-BRIDGE] connected %s:%d" % (self._host, self._port))
            return True
        except Exception as exc:  # noqa: BLE001 - 桥不能因为网络挂掉就崩视觉
            print("[V6-BRIDGE] connect failed: %s（下次再试）" % exc)
            self._sock = None
            return False

    def _drop(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:  # noqa: BLE001
                pass
            self._sock = None

    # ── 主入口 ──────────────────────────────────────────────────
    def send(self, rows, task_id=None, now=None):
        """把这一帧的 results 发出去。返回实际发出的件数。"""
        import time as _t
        now = now if now is not None else _t.monotonic()
        if now - self._last < self._interval:
            return 0
        self._last = now

        try:
            data = encode_batch_targets(rows, self._task_id if task_id is None else task_id)
        except Exception as exc:  # noqa: BLE001
            print("[V6-BRIDGE] encode failed: %s" % exc)
            return 0

        n = data[0]
        if n == 0:
            # 一帧里一件都没认出来 —— 不发，避免空帧把树莓派的槽占掉
            self.skipped_frames += 1
            return 0

        if not self._enable:
            print("[V6-BRIDGE] (disabled) would send %d item(s), %d bytes" % (n, len(data)))
            self.sent_frames += 1
            self.sent_items += n
            return n

        if not self._ensure():
            return 0
        try:
            self._sock.sendall(data)
        except Exception as exc:  # noqa: BLE001
            print("[V6-BRIDGE] send failed: %s -> 重连" % exc)
            self._drop()
            return 0

        self.sent_frames += 1
        self.sent_items += n
        return n

    def close(self):
        self._drop()


# ── 自检（电脑上直接跑：py -3 v6_bridge.py）────────────────────────
def _selftest():
    # Windows 控制台默认 GBK，打不出 ✅ 之类的字符会 UnicodeEncodeError。
    # 与 工具/pi_blit_png.py 用同一套处理。
    import sys as _sys
    for _s in (_sys.stdout, _sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    ok = 0
    fail = []

    def chk(name, cond):
        nonlocal ok
        if cond:
            ok += 1
        else:
            fail.append(name)

    def row(bin_id, bbox, frac=0.9, stale=False):
        return {"bin": bin_id, "bbox": bbox, "color_fraction": frac,
                "color": "cyan", "shape": "cube", "stale": stale}

    # 1. 基本编码：2 件，bin=1 和 3
    data = encode_batch_targets([row(1, (10, 20, 40, 40)), row(3, (100, 120, 30, 30))], 7)
    chk("头部 target_count", data[0] == 2)
    chk("头部 task_id 大端", data[1:3] == b"\x00\x07")
    chk("总长 = 3 + 2*7", len(data) == 3 + 2 * TARGET_BYTES)
    chk("第1件 id_byte = 1", data[3] == 1)
    chk("第1件 angle = 0xFF", data[3 + 6] == 0xFF)
    chk("第2件 id_byte = 3", data[10] == 3)

    # 2. 中心像素 = left + w/2, top + h/2
    t1 = data[3:10]
    cx = int.from_bytes(t1[2:4], "big")
    cy = int.from_bytes(t1[4:6], "big")
    chk("bbox(10,20,40,40) 中心 = (30,40)", (cx, cy) == (30, 40))

    # 3. HOLD 灰框（bin=None）必须被丢掉
    data = encode_batch_targets([row(None, (1, 2, 3, 4), stale=True), row(5, (10, 10, 20, 20))], 7)
    chk("bin=None 被丢，只剩 1 件", data[0] == 1)
    chk("幸存的是 bin=5", data[3] == 5)

    # 4. 全都不认识 → 空帧（count=0），且是合法的
    data = encode_batch_targets([row(None, (1, 2, 3, 4))], 7)
    chk("全丢时 count=0", data[0] == 0)
    chk("空帧长度 = 3", len(data) == 3)

    # 5. 越界 bin 也要丢（0 和 7）
    data = encode_batch_targets([row(0, (1, 2, 3, 4)), row(7, (1, 2, 3, 4)), row(2, (5, 5, 10, 10))], 7)
    chk("bin=0/7 都丢掉", data[0] == 1 and data[3] == 2)

    # 6. confidence 由 color_fraction 合成
    data = encode_batch_targets([row(1, (0, 0, 10, 10), frac=0.83)], 7)
    chk("color_fraction 0.83 -> conf 83", data[4] == 83)
    data = encode_batch_targets([row(1, (0, 0, 10, 10), frac=1.5)], 7)
    chk("frac>1 被夹到 100", data[4] == 100)

    # 7. task_id 边界
    try:
        encode_batch_targets([], 70000)
        chk("task_id 越界应抛错", False)
    except ValueError:
        chk("task_id 越界抛 ValueError", True)

    # 8. 节流：间隔内不发
    s = BatchSender(enable=False, interval=10.0)
    n1 = s.send([row(1, (0, 0, 10, 10))], now=1000.0)
    n2 = s.send([row(1, (0, 0, 10, 10))], now=1000.05)
    chk("首次发出", n1 == 1)
    chk("间隔内第二次不发", n2 == 0)

    # 9. 空帧不发
    s2 = BatchSender(enable=False, interval=0.0)
    chk("空帧返回 0", s2.send([row(None, (0, 0, 1, 1))], now=1.0) == 0)

    print("=" * 56)
    if fail:
        print("失败 %d 项：" % len(fail))
        for f in fail:
            print("  ✗ " + f)
        return 1
    print("自检：%d 项全部通过 ✅" % ok)
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
