#!/usr/bin/env python3
"""树莓派侧：V6 → 树莓派 的独立验证监听器（2026-09-18）

【为什么单独写一个】
真实主链 `run_chain.py` 会在 8765 起监听，但**真实模式缺 [DropPoints] 会立刻退出**。
所以为了单独验证「MaixCAM 上的 V6 能不能把数据发过来、字节对不对」，
这里起一个只解析 + 打印的监听器，不碰任何硬件、不发任何指令。

【跑法（在树莓派上）】
    cd /opt/ec-chain/deploy
    PYTHONPATH=/opt/ec-chain/src python3 pi_vision_listen.py

然后在 MaixVision 里跑 V6（桥的 ENABLE_NETWORK=True）。
这里会实时打印每一帧收到了什么。

【它验的是什么】
- 能不能连上（连不上 = 树莓派没监听 / IP 不对 / 防火墙）
- 字节对不对（用**和生产完全同一个** parse_batch_targets 解析，不是自己写的）
- box_id 对不对（应是 1..6；出现越界值说明 V6 那边 bin 不对）
- 件数对不对（HOLD 灰框不该出现在里面）

【安全】只读、不写任何硬件、不碰串口、不碰 GPIO。
"""
import socket
import sys
import time

sys.path.insert(0, "/opt/ec-chain/src")

try:
    from electrical_control.rpi.vision_ingest import parse_batch_targets
except ImportError as exc:  # pragma: no cover
    print("导入失败：%s" % exc)
    print("要在项目里跑：PYTHONPATH=/opt/ec-chain/src python3 pi_vision_listen.py")
    raise SystemExit(2)

HOST = "0.0.0.0"
PORT = 8765
MAX_FRAME = 4096          # 256 件 * 7 + 3 也才 1795；给足余量
IDLE_TIMEOUT_S = 30.0     # 连接后多久没数据就断开重收


def describe(data: bytes) -> str:
    """把一帧 BATCH_TARGETS 解成人话。解析失败把原因说清楚。"""
    try:
        bt = parse_batch_targets(data)
    except Exception as exc:  # noqa: BLE001
        return "  ✗ 解析失败: %s\n    原始字节(前64): %s" % (exc, data[:64].hex(" "))

    if not bt.targets:
        return "  收到空帧 task_id=%d（V6 那一帧没认出任何货格）" % bt.task_id

    lines = ["  ✓ task_id=%d  件数=%d" % (bt.task_id, len(bt.targets))]
    for t in bt.targets:
        lines.append("      seq=%d  box_id=%s  px=(%d,%d)  conf=%s"
                     % (t.target_seq, t.box_id, t.pixel_x, t.pixel_y,
                        getattr(t, "confidence", "?")))
    bad = [t.box_id for t in bt.targets if t.box_id is None or not (1 <= t.box_id <= 6)]
    if bad:
        lines.append("      ⚠️ 有越界 box_id: %s（V6 的 bin 不该出现这些值）" % bad)
    return "\n".join(lines)


def main() -> int:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(1)
    print("=" * 62)
    print("V6 → 树莓派 验证监听器")
    print("  监听 %s:%d   等 MaixCAM 连过来" % (HOST, PORT))
    print("  Ctrl-C 退出。只打印，不发任何指令、不碰硬件。")
    print("=" * 62)

    frames = 0
    while True:
        try:
            conn, addr = srv.accept()
        except KeyboardInterrupt:
            print("\n退出。共收到 %d 帧。" % frames)
            return 0

        print("\n[%s] 连上了：%s" % (time.strftime("%H:%M:%S"), addr[0]))
        conn.settimeout(IDLE_TIMEOUT_S)
        buf = b""
        try:
            while True:
                chunk = conn.recv(1024)
                if not chunk:
                    print("  (对端断开)")
                    break
                buf += chunk
                # BATCH_TARGETS 是自描述长度的：前 3 字节 head + count*7
                while len(buf) >= 3:
                    need = 3 + buf[0] * 7
                    if len(buf) < need:
                        break
                    frame, buf = buf[:need], buf[need:]
                    frames += 1
                    print("[%s] 第 %d 帧，%d 字节"
                          % (time.strftime("%H:%M:%S"), frames, len(frame)))
                    print(describe(frame))
        except socket.timeout:
            print("  （%ds 无数据，断开，等待重连）" % int(IDLE_TIMEOUT_S))
        except Exception as exc:  # noqa: BLE001
            print("  异常: %s" % exc)
        finally:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
