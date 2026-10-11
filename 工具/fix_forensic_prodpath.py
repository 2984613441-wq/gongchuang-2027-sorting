# -*- coding: utf-8 -*-
"""把 forensic_v6_frame.py 的 load_production() 改成"多目录搜索"。
MaixVision 只把当前打开的那一个文件推到 /tmp/maixpy_run/ 再跑，
所以取证脚本旁边不会有 V6 —— 必须自己找。
"""
import io, os, shutil, sys, time, py_compile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F = os.path.join(ROOT, "视觉", "src", "maixcam_deploy", "forensic_v6_frame.py")

OLD = '''def load_production():
    """import 生产文件本体（只用它的常量和纯函数）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(here, "stage1_color_v6_send.py")
    if not os.path.exists(src):
        raise SystemExit(
            "找不到 %s\\n本脚本必须和 stage1_color_v6_send.py 放在同一目录。" % src)
'''

NEW = '''TARGET_NAME = "stage1_color_v6_send.py"


def _find_production():
    """按候选目录找生产文件；返回 (路径, 找过的路径列表)。"""
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [here]
    if os.environ.get("FORENSIC_PROD_DIR"):
        cands.append(os.environ["FORENSIC_PROD_DIR"])
    cands += ["/root/forensic", "/tmp/maixpy_run", "/root", os.getcwd()]
    tried = []
    for d in cands:
        p = os.path.join(d, TARGET_NAME)
        if os.path.exists(p):
            return p, tried
        tried.append(p)
    return None, tried


def load_production():
    """import 生产文件本体（只用它的常量和纯函数）。

    ⚠️ 2026-09-21 修：MaixVision 运行时只把**当前打开的那一个文件**推到
    /tmp/maixpy_run/ 再执行，所以取证脚本旁边**不会**有 V6。
    因此改为按候选目录搜索，并打印**完整路径 + sha256**，
    用来确认加载的正是现场实际在跑的那一份（hash 对不上就说明版本不同，读数作废）。
    """
    src, tried = _find_production()
    if src is None:
        raise SystemExit(
            "找不到 %s。找过这些地方：\\n  %s\\n"
            "→ 把你 MaixVision 项目里那份 %s 复制到 /root/forensic/ 即可。"
            % (TARGET_NAME, "\\n  ".join(tried), TARGET_NAME))
    import hashlib
    with open(src, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    print("[forensic] production = %s" % src)
    print("[forensic] sha256     = %s" % digest)
'''


def main():
    s = io.open(F, encoding="utf-8").read()
    n = s.count(OLD)
    print("锚点命中 %d 次（必须 1）" % n)
    if n != 1:
        return 1
    if "--apply" not in sys.argv:
        print("DRY-RUN OK. 加 --apply 落盘。")
        return 0
    shutil.copy2(F, F + ".bak-prodfind-" + time.strftime("%Y%m%d-%H%M%S"))
    io.open(F, "w", encoding="utf-8", newline="").write(s.replace(OLD, NEW, 1))
    py_compile.compile(F, doraise=True)
    print("已改 + py_compile OK: %s" % os.path.basename(F))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
