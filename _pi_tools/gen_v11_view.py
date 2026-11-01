"""从 yolo_v7_cn_view.py 生成 yolo_v11_cn_view.py。

只改三处：MODEL_NAME 默认值、文件头说明、打印横幅。
其余逻辑（中文绘制、颜色兜底、加载顺序）原样保留 —— v7 版已在设备上验证可用。
"""

from pathlib import Path

SRC = Path("_pi_tools/maixcam_scripts/yolo_v7_cn_view.py")
DST = Path("_pi_tools/maixcam_scripts/yolo_v11_cn_view.py")

HEAD_V11 = (
    '"""MaixCAM v11 六类模型 · 中文标签观测版  2026-10-28 深夜\n'
    "\n"
    "## v11 是什么\n"
    "\n"
    "    v11 = v9 数据（昨晚 + 今早复核） + 20261028b 批次（用户复核后）\n"
    "    训练指标: mAP50 0.980 / mAP50-95 0.593（历史最高）/ P 0.958（历史最高）/ R 0.943\n"
    "    逐类 mAP50: cube 0.991 · cuboid 0.965 · cylinder 0.925\n"
    "                penta 0.970 · cone 0.986 · tetra 0.995\n"
    "    独立帧 A/B（139 帧未训练）: conf 0.68/0.74，高置信框 273（v9 是 213）\n"
    "\n"
    "## 与 v7 版的区别\n"
    "\n"
    "    只改了两处：MODEL_NAME 默认值、本段说明。\n"
    "    其余逻辑（中文绘制、颜色兜底、加载顺序）原样保留，因为 v7 版已验证可用。\n"
    "\n"
    "## v7 版原始说明\n"
)


def main() -> int:
    s = SRC.read_text(encoding="utf-8")

    # ① 模型名默认值
    before = '"yolo11n_6c_v7_448_cv181x"'
    after = '"yolo11n_6c_v11_448_cv181x"'
    assert before in s, "模型名未匹配"
    s = s.replace(before, after)

    # ② 文件头：把原来的 docstring 开头替换成 v11 说明（保留后续内容）
    old_head = '"""MaixCAM v7 六类模型 · 中文标签观测版  2026-10-28\n'
    assert old_head in s, "文件头未匹配"
    s = s.replace(old_head, HEAD_V11, 1)

    # ③ 打印横幅
    s = s.replace("MaixCAM v7 六类 · 中文标签观测版",
                  "MaixCAM v11 六类 · 中文标签观测版")

    # ④ 模型缺失提示里的文件名
    s = s.replace("yolo11n_6c_v7_448_cv181x.cvimodel / .mud",
                  "yolo11n_6c_v11_448_cv181x.cvimodel / .mud")

    DST.write_bytes(s.encode("utf-8"))
    print("  已生成: %s  (%d 字节)" % (DST, DST.stat().st_size))
    for ln in s.splitlines():
        if "MODEL_NAME" in ln and "environ" in ln:
            print("    " + ln.strip())
    raw = DST.read_bytes()
    print("  CRLF: %s" % ("YES" if b"\r" in raw else "NO"))
    # 语法检查
    try:
        compile(raw.decode("utf-8"), str(DST), "exec")
        print("  ✅ 语法检查通过")
    except SyntaxError as e:
        print("  ❌ 语法错误: %s" % e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
