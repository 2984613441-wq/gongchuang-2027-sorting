#!/usr/bin/env python3
"""Compare host trees with Raspberry Pi trees through one SSH manifest.

The script compares bytes, not normalized text.  This is intentional: a
different line ending is a different deployment artifact and must be visible.
Cache directories are skipped because they are generated artifacts; inspect
them separately with the commands in the deployment audit.

Example (run from the workspace root on Windows):

    python scripts/compare_deploy_trees.py --ssh pi@raspberrypi.local \
      --map "电控/src=/home/pi/电控/src" \
      --map "视觉/src=/home/pi/视觉/src" \
      --map "集成=/home/pi/集成" \
      --map "工具=/home/pi/工具" \
      --out deploy-diff.csv

The remote side executes this same file over ``python3 -`` and emits JSON;
only the standard library is required on either host.
"""

from __future__ import annotations

import argparse
import base64
import csv
import datetime as _dt
import hashlib
import json
import os
import socket
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
TEXT_SUFFIXES = {
    ".c",
    ".cfg",
    ".cmake",
    ".conf",
    ".csv",
    ".h",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".service",
    ".sh",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
TEXT_NAMES = {"Makefile", "CMakeLists.txt", "Dockerfile"}
FILE_FIELDS = ("kind", "size", "lines", "mtime_ns", "sha256")
CONTENT_FIELDS = ("kind", "size", "lines", "sha256")


def _mtime_utc(st: os.stat_result) -> str:
    return _dt.datetime.fromtimestamp(
        st.st_mtime, tz=_dt.timezone.utc
    ).isoformat()


def _is_text(path: Path) -> bool:
    return path.name in TEXT_NAMES or path.suffix.lower() in TEXT_SUFFIXES


def _file_meta(path: Path) -> Dict[str, Any]:
    """Return metadata while hashing and counting text lines in one pass."""

    st = path.stat()
    digest = hashlib.sha256()
    size = 0
    newline_count = 0
    last_byte = None
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
            newline_count += chunk.count(b"\n")
            last_byte = chunk[-1]

    lines = None
    if _is_text(path):
        lines = newline_count + int(size > 0 and last_byte != 10)
    return {
        "kind": "file",
        "size": size,
        "lines": lines,
        "mtime_ns": st.st_mtime_ns,
        "mtime_utc": _mtime_utc(st),
        "sha256": digest.hexdigest(),
    }


def _manifest(root: str) -> Dict[str, Any]:
    """Build a manifest keyed by POSIX relative paths."""

    base = Path(root).expanduser()
    result: Dict[str, Any] = {"root": str(base), "files": {}}
    if not base.is_dir():
        result["error"] = "not a directory"
        return result

    files: Dict[str, Any] = result["files"]
    for dirpath, dirnames, filenames in os.walk(str(base), followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            relative = path.relative_to(base).as_posix()
            try:
                if path.is_symlink():
                    st = path.lstat()
                    files[relative] = {
                        "kind": "symlink",
                        "size": None,
                        "lines": None,
                        "mtime_ns": st.st_mtime_ns,
                        "mtime_utc": _mtime_utc(st),
                        "sha256": None,
                        "target": os.readlink(str(path)),
                    }
                elif path.is_file():
                    files[relative] = _file_meta(path)
            except OSError as exc:
                files[relative] = {"kind": "error", "error": repr(exc)}
    return result


def _parse_maps(values: Iterable[str]) -> List[Tuple[str, str]]:
    maps: List[Tuple[str, str]] = []
    seen = set()
    for value in values:
        if "=" not in value:
            raise SystemExit(f"--map 需要 LOCAL_REL=REMOTE_ABS：{value!r}")
        local_rel, remote_abs = value.split("=", 1)
        local_rel, remote_abs = local_rel.strip(), remote_abs.strip()
        if not local_rel or not remote_abs:
            raise SystemExit(f"--map 不能为空：{value!r}")
        if local_rel in seen:
            raise SystemExit(f"--map 重复：{local_rel}")
        seen.add(local_rel)
        maps.append((local_rel, remote_abs))
    return maps


def _remote_worker() -> int:
    if len(sys.argv) != 3:
        print("usage: --remote-worker BASE64_JSON", file=sys.stderr)
        return 2
    try:
        raw = base64.urlsafe_b64decode(sys.argv[2].encode("ascii"))
        roots = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        print(f"invalid remote manifest request: {exc}", file=sys.stderr)
        return 2
    output = {
        "host": socket.gethostname(),
        "python": sys.version,
        "roots": {label: _manifest(path) for label, path in roots.items()},
    }
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    return 0


def _remote_manifest(
    ssh_target: str, remote_python: str, roots: Dict[str, str]
) -> Dict[str, Any]:
    payload = base64.urlsafe_b64encode(
        json.dumps(roots, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    source = Path(__file__).read_bytes()
    completed = subprocess.run(
        [ssh_target.split(" ", 1)[0], remote_python, "-", "--remote-worker", payload],
        input=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"ssh manifest failed ({completed.returncode}): "
            f"{completed.stderr.decode('utf-8', 'replace').strip()}"
        )
    try:
        return json.loads(completed.stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "remote output is not JSON; ssh banners must go to stderr: "
            + completed.stdout.decode("utf-8", "replace")[:500]
        ) from exc


def _row(
    label: str,
    local_root: str,
    remote_root: str,
    relative: str,
    status: str,
    local: Dict[str, Any] | None,
    remote: Dict[str, Any] | None,
    changed: List[str],
) -> Dict[str, Any]:
    return {
        "root": label,
        "relative_path": relative,
        "status": status,
        "changed_fields": ";".join(changed),
        "local_root": local_root,
        "remote_root": remote_root,
        "local_kind": (local or {}).get("kind"),
        "remote_kind": (remote or {}).get("kind"),
        "local_size": (local or {}).get("size"),
        "remote_size": (remote or {}).get("size"),
        "local_lines": (local or {}).get("lines"),
        "remote_lines": (remote or {}).get("lines"),
        "local_mtime_utc": (local or {}).get("mtime_utc"),
        "remote_mtime_utc": (remote or {}).get("mtime_utc"),
        "local_mtime_ns": (local or {}).get("mtime_ns"),
        "remote_mtime_ns": (remote or {}).get("mtime_ns"),
        "local_sha256": (local or {}).get("sha256"),
        "remote_sha256": (remote or {}).get("sha256"),
    }


def _compare_root(
    label: str, local: Dict[str, Any], remote: Dict[str, Any]
) -> List[Dict[str, Any]]:
    local_files = local.get("files", {})
    remote_files = remote.get("files", {})
    local_error, remote_error = local.get("error"), remote.get("error")
    if local_error or remote_error:
        status = "BOTH_ROOT_MISSING" if local_error and remote_error else (
            "LOCAL_ROOT_MISSING" if local_error else "REMOTE_ROOT_MISSING"
        )
        return [_row(
            label,
            str(local.get("root", "")),
            str(remote.get("root", "")),
            "__ROOT__",
            status,
            {"kind": "error", "error": local_error} if local_error else None,
            {"kind": "error", "error": remote_error} if remote_error else None,
            [],
        )]

    rows: List[Dict[str, Any]] = []
    for relative in sorted(set(local_files) | set(remote_files)):
        left, right = local_files.get(relative), remote_files.get(relative)
        if left is None:
            rows.append(_row(label, local["root"], remote["root"], relative,
                             "ONLY_REMOTE", None, right, []))
            continue
        if right is None:
            rows.append(_row(label, local["root"], remote["root"], relative,
                             "ONLY_LOCAL", left, None, []))
            continue
        changed = [field for field in FILE_FIELDS if left.get(field) != right.get(field)]
        if left.get("kind") == "symlink" or right.get("kind") == "symlink":
            if left.get("target") != right.get("target"):
                changed.append("target")
        if changed:
            # scp/rsync may not preserve nanosecond mtimes.  Keep that drift
            # visible, but distinguish it from a byte/content mismatch.
            status = "MTIME_ONLY" if not any(
                field in CONTENT_FIELDS for field in changed
            ) else "DIFF"
            rows.append(_row(label, local["root"], remote["root"], relative,
                             status, left, right, changed))
        else:
            rows.append(_row(label, local["root"], remote["root"], relative,
                             "SAME", left, right, []))
    return rows


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--remote-worker":
        return _remote_worker()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh", required=True, help="SSH target, e.g. pi@raspberrypi.local")
    parser.add_argument("--remote-python", default="python3")
    parser.add_argument("--local-root", default=".")
    parser.add_argument(
        "--map", action="append", dest="maps", metavar="LOCAL_REL=REMOTE_ABS",
        help="repeatable; defaults to the four project trees",
    )
    parser.add_argument("--out", default="deploy-diff.csv")
    parser.add_argument("--all", action="store_true", help="also write SAME rows")
    args = parser.parse_args()

    maps = _parse_maps(args.maps or [
        "电控/src=/home/pi/电控/src",
        "视觉/src=/home/pi/视觉/src",
        "集成=/home/pi/集成",
        "工具=/home/pi/工具",
    ])
    local_root = Path(args.local_root).expanduser().resolve()
    local_manifests = {
        label: _manifest(str(local_root / local_rel))
        for label, local_rel in maps
    }
    remote_manifests = _remote_manifest(
        args.ssh,
        args.remote_python,
        {label: remote for label, remote in maps},
    ).get("roots", {})

    rows: List[Dict[str, Any]] = []
    for label, _ in maps:
        rows.extend(_compare_root(
            label,
            local_manifests[label],
            remote_manifests.get(label, {"root": "", "error": "missing JSON root"}),
        ))

    output_rows = rows if args.all else [row for row in rows if row["status"] != "SAME"]
    columns = [
        "root", "relative_path", "status", "changed_fields",
        "local_root", "remote_root", "local_kind", "remote_kind",
        "local_size", "remote_size", "local_lines", "remote_lines",
        "local_mtime_utc", "remote_mtime_utc", "local_mtime_ns", "remote_mtime_ns",
        "local_sha256", "remote_sha256",
    ]
    if args.out == "-":
        writer = csv.DictWriter(sys.stdout, fieldnames=columns)
        writer.writeheader()
        writer.writerows(output_rows)
    else:
        with Path(args.out).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(output_rows)

    counts = Counter(row["status"] for row in rows)
    summary_stream = sys.stderr if args.out == "-" else sys.stdout
    print(
        f"写入 {args.out}：{len(output_rows)} 行（总文件项 {len(rows)}）",
        file=summary_stream,
    )
    print(
        "状态：" + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())),
        file=summary_stream,
    )
    return 0 if not any(row["status"] != "SAME" for row in rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
