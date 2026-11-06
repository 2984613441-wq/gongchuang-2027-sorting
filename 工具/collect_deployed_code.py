# -*- coding: utf-8 -*-
"""把树莓派 / MaixCAM 上**实际部署的代码**拉回本仓库并生成清单（2026-11-05）。

为什么需要
----------
设备上跑的代码可能与我们仓库里的不一致（现场改过、拷过去没同步）。
“接口对齐”前必须先把**设备上的真身**取回来，逐项比对。

做什么
------
1. `--dry-run`：只打印要执行的 ssh/tar 命令，不连设备；
2. 默认：用 `ssh + tar` 把指定目录/文件打成 tar 流拉回本地，
   解到 `_deployed_snapshot/<时间戳>/<device>/`，并写 `manifest.json`（逐文件 sha256）；
3. `--diff`：把最近一次快照与本地仓库比对，输出
   「只在设备 / 只在仓库 / 内容不同 / 无对应关系」四类。

边界
----
* 只读设备：只用 `tar` 读文件、`git rev-parse` 读 HEAD，不写设备、不重启服务。
* 需要本机有 `ssh`（Windows 10+ 自带 OpenSSH）；`--dry-run` 不需要网络。

用法
----
```powershell
python 工具/collect_deployed_code.py --dry-run
python 工具/collect_deployed_code.py                 # 拉取（默认不含模型权重）
python 工具/collect_deployed_code.py --with-models   # 连模型一起拉（很慢）
python 工具/collect_deployed_code.py --diff          # 与本地仓库比对
python 工具/collect_deployed_code.py --self-test      # 无设备自检
```
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAP_ROOT = ROOT / "_deployed_snapshot"

# 设备与要拉取的东西（路径都是设备上的绝对路径）
DEVICES = {
    "pi": {
        "ssh": "pi@172.20.10.8",
        "paths": [
            "/home/pi/电控/src",
            "/home/pi/电控/deploy",
            "/home/pi/sorting_config.ini",
            "/home/pi/calibration_config.ini",
            "/home/pi/p_look2.py",
            "/home/pi/pi_pw.py",
            "/home/pi/pi_turntable.py",
            "/home/pi/pi_cam2_capture.py",
            "/home/pi/pi_cam2_stream.py",
            "/home/pi/pi_cam2_grab.py",
            "/home/pi/check_turntable_strategy.py",
        ],
        "models": [],
    },
    "maixcam": {
        "ssh": "root@172.20.10.9",
        "paths": [
            "/root/yolo_v11_send.py",
            "/root/stage1_color_v6_send.py",
        ],
        "models": ["/root/my_models"],
    },
}

# 快照路径 → 本地仓库路径（用于 --diff；未列出的会被归为“无对应关系”）
PATH_MAP = [
    ("pi", "/home/pi/电控/src/electrical_control", "电控/src/electrical_control"),
    ("pi", "/home/pi/电控/deploy", "电控/deploy"),
    ("pi", "/home/pi/sorting_config.ini", "电控/sorting_config.ini"),
    ("pi", "/home/pi/calibration_config.ini", "电控/calibration_config.ini"),
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run(cmd: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def ssh_probe(ssh: str, paths: list[str]) -> list[str]:
    """一次 ssh 回来：清单里哪些路径在设备上存在。"""
    script = "; ".join(
        "if [ -e %s ]; then echo EXIST %s; fi" % (_q(p), _q(p)) for p in paths
    )
    proc = _run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
                 ssh, "bash -lc %s" % _q(script)], timeout=30)
    if proc.returncode != 0:
        raise RuntimeError("ssh 失败：%s" % proc.stderr.decode("utf-8", "replace")[:300])
    found = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        if line.startswith("EXIST "):
            found.append(line[len("EXIST "):].strip())
    return found


def _q(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def fetch_device(name: str, spec: dict, dest: Path, *, with_models: bool) -> dict:
    paths = list(spec["paths"])
    if with_models:
        paths += spec.get("models", [])
    present = ssh_probe(spec["ssh"], paths)
    if not present:
        raise RuntimeError("%s：清单里的路径一个都不存在" % name)

    rel = [p.lstrip("/") for p in present]
    tar_cmd = "tar czf - -C / " + " ".join(_q(r) for r in rel)
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
         spec["ssh"], "bash -lc %s" % _q(tar_cmd)],
        capture_output=True, timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError("%s：tar 拉取失败 %s" % (name, proc.stderr.decode("utf-8", "replace")[:300]))

    dest.mkdir(parents=True, exist_ok=True)
    files = []
    with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:gz") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            safety = Path(member.name)
            if safety.is_absolute() or ".." in safety.parts:
                continue
            out = dest / safety
            out.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            data = src.read() if src else b""
            out.write_bytes(data)
            files.append({"path": "/" + member.name, "rel": member.name,
                          "bytes": len(data), "sha256": sha256_bytes(data)})

    head = None
    try:
        p = _run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6",
                  spec["ssh"], "bash -lc %s" % _q(
                      "cd /home/pi/电控 2>/dev/null && git rev-parse HEAD || "
                      "cd /root && git rev-parse HEAD 2>/dev/null || echo NOGIT")],
                 timeout=30)
        out = p.stdout.decode("utf-8", "replace").strip()
        head = None if ("NOGIT" in out or not out) else out.splitlines()[-1]
    except Exception:
        head = None

    return {"device": name, "ssh": spec["ssh"], "files": files, "git_head": head,
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")}


# --------------------------------------------------------------------------- #
# --diff：快照 vs 本地仓库
# --------------------------------------------------------------------------- #
def map_snapshot_path(device: str, abs_path: str) -> str | None:
    for dev, prefix, local in PATH_MAP:
        if dev != device:
            continue
        if abs_path == prefix or abs_path.startswith(prefix + "/"):
            tail = abs_path[len(prefix):].lstrip("/")
            return local if not tail else "%s/%s" % (local, tail)
    return None


def diff_snapshot(snapshot_dir: Path) -> dict:
    manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    only_snap, only_repo, changed, unmapped = [], [], [], []
    seen_local = set()
    for dev, info in manifest["devices"].items():
        for f in info["files"]:
            local = map_snapshot_path(dev, f["path"])
            if local is None:
                unmapped.append({"device": dev, "path": f["path"]})
                continue
            seen_local.add(local)
            lp = ROOT / local
            if not lp.exists():
                only_snap.append({"device": dev, "path": f["path"], "local": local})
                continue
            if sha256_file(lp) != f["sha256"]:
                changed.append({"device": dev, "path": f["path"], "local": local})
    for dev, prefix, local_root in PATH_MAP:
        base = ROOT / local_root
        if not base.exists():
            continue
        files = [base] if base.is_file() else [p for p in base.rglob("*") if p.is_file()]
        for p in files:
            rel = p.relative_to(ROOT).as_posix()
            if rel not in seen_local:
                only_repo.append({"local": rel})
    return {"snapshot": str(snapshot_dir), "only_in_device": only_snap,
            "only_in_repo": only_repo, "content_differs": changed,
            "unmapped": unmapped}


def print_diff(result: dict) -> None:
    print("快照：%s" % result["snapshot"])
    for key, title in (("only_in_device", "只在设备上（仓库没有）"),
                       ("only_in_repo", "只在仓库里（设备没有）"),
                       ("content_differs", "内容不同（需要合并）"),
                       ("unmapped", "无对应关系（人工判断）")):
        items = result[key]
        print("\n== %s：%d 项 ==" % (title, len(items)))
        for it in items[:40]:
            print("   ", it.get("path") or it.get("local"),
                  "→", it.get("local", ""))
        if len(items) > 40:
            print("    ... 还有 %d 项" % (len(items) - 40))


# --------------------------------------------------------------------------- #
# --self-test
# --------------------------------------------------------------------------- #
def self_test() -> int:
    tmp = ROOT / "_deployed_snapshot" / "_selftest"
    if tmp.exists():
        shutil.rmtree(tmp)
    (tmp / "pi" / "home/pi/电控/deploy").mkdir(parents=True)
    fake = tmp / "pi" / "home/pi/电控/deploy" / "run_chain.py"
    fake.write_text("# fake\n", encoding="utf-8")
    (tmp / "pi" / "home/pi/电控/src/electrical_control").mkdir(parents=True)
    (tmp / "pi" / "home/pi/电控/src/electrical_control" / "x.py").write_text("", encoding="utf-8")
    manifest = {"devices": {"pi": {"files": [
        {"path": "/home/pi/电控/deploy/run_chain.py", "sha256": sha256_file(fake)},
        {"path": "/home/pi/电控/src/electrical_control/x.py",
         "sha256": sha256_bytes(b"")},
        {"path": "/home/pi/unknown.bin", "sha256": sha256_bytes(b"?")},
    ]}}}
    (tmp / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = diff_snapshot(tmp)
    assert result["only_in_device"], result
    assert result["unmapped"], result
    assert any(it["local"] == "电控/deploy/run_chain.py" for it in result["content_differs"]) \
        or any(it["local"] == "电控/deploy/run_chain.py" for it in result["only_in_repo"]), result
    print("self-test OK：diff 分类（只在设备/无对应/内容不同）工作正常")
    shutil.rmtree(tmp)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="拉取设备上实际部署的代码并比对")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--diff", action="store_true", help="用最近一次快照做比对")
    ap.add_argument("--snapshot", default="", help="指定快照目录（配合 --diff）")
    ap.add_argument("--devices", default="pi,maixcam")
    ap.add_argument("--with-models", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    if args.diff:
        base = Path(args.snapshot) if args.snapshot else _latest_snapshot()
        if base is None:
            print("没有快照可比对（先跑一次采集）")
            return 1
        print_diff(diff_snapshot(base))
        return 0

    names = [n.strip() for n in args.devices.split(",") if n.strip()]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = SNAP_ROOT / stamp
    for name in names:
        spec = DEVICES.get(name)
        if spec is None:
            print("未知设备：%s（可选 %s）" % (name, list(DEVICES)))
            continue
        paths = list(spec["paths"]) + (spec.get("models", []) if args.with_models else [])
        rel = [p.lstrip("/") for p in paths]
        tar_cmd = "tar czf - -C / " + " ".join(_q(r) for r in rel)
        if args.dry_run:
            print("[dry-run] %s（%s）" % (name, spec["ssh"]))
            print("  探测：ssh %s 'ls -d %s'" % (spec["ssh"], " ".join(paths)))
            print("  拉取：ssh %s %s > %s.tar.gz" % (spec["ssh"], _q(tar_cmd),
                                                  dest / name))
            continue
        print("拉取 %s ..." % name)
        try:
            info = fetch_device(name, spec, dest / name, with_models=args.with_models)
        except Exception as exc:
            print("  失败：%s" % exc)
            continue
        (dest / name / "manifest.device.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        print("  OK %d 个文件，git_head=%s" % (len(info["files"]), info["git_head"]))

    if args.dry_run:
        return 0

    manifest = {"snapshot": str(dest), "created_at": stamp, "devices": {}}
    for sub in dest.iterdir() if dest.exists() else []:
        mf = sub / "manifest.device.json"
        if mf.exists():
            manifest["devices"][sub.name] = json.loads(mf.read_text(encoding="utf-8"))
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False,
                                                   indent=2), encoding="utf-8")
    print("\n快照已写入：%s" % dest)
    print("比对：python 工具/collect_deployed_code.py --diff")
    return 0


def _latest_snapshot() -> Path | None:
    if not SNAP_ROOT.exists():
        return None
    dirs = sorted([p for p in SNAP_ROOT.iterdir()
                   if p.is_dir() and (p / "manifest.json").exists()],
                  key=lambda p: p.name)
    return dirs[-1] if dirs else None


if __name__ == "__main__":
    raise SystemExit(main())
