#!/usr/bin/env python3
"""绕开 Windows 沙箱对「命名管道/多进程」的封锁，让 ultralytics 能在本机训练。

## 症状

    File "...\\multiprocessing\\connection.py", line 575, in Pipe
    PermissionError: [WinError 5] 拒绝访问。

出现在 `ultralytics/data/dataset.py: cache_labels()` 里的
`with ThreadPool(NUM_THREADS) as pool:` —— 沙箱禁止创建 named pipe，
任何 `multiprocessing`/`ThreadPool` 都会炸。

## 解决

把 `YOLODataset.cache_labels` 换成**串行版**（同样的 hooks，只是不建进程池）；
同时训练时 `workers=0`（数据加载也不开子进程）。

用法：在训练脚本最前面 `import _ultra_patch` 即可（本文件导入时自动打补丁）。
"""

from __future__ import annotations


def apply() -> bool:
    try:
        from pathlib import Path

        import ultralytics.data.dataset as ds
        from ultralytics.data.utils import save_dataset_cache_file
        DATASET_CACHE_VERSION = ds.DATASET_CACHE_VERSION
        from ultralytics.utils import LOGGER
    except Exception as e:  # pragma: no cover
        print("[ultra_patch] 导入 ultralytics 失败：%r" % e)
        return False

    def serial_cache_labels(self, path=Path("./labels.cache")):
        """`cache_labels` 的串行实现（不建 ThreadPool）。"""
        x = {"labels": []}
        nm, nf, ne, nc, msgs = 0, 0, 0, 0, []
        total = len(self.im_files)
        func, iterable = self.verify_args()
        for item in iterable:
            result = func(item)       # verify_image_label 接受 1 个元组参数（与 pool.imap 一致）
            label, nm_f, nf_f, ne_f, nc_f, msg = self.result_to_label(result)
            nm += nm_f
            nf += nf_f
            ne += ne_f
            nc += nc_f
            if label is not None:
                x["labels"].append(label)
            if msg:
                msgs.append(msg)
        if msgs:
            LOGGER.info("\n".join(msgs))
        if nf == 0 and x["labels"]:
            if self.augment:
                raise ValueError(f"{self.prefix}No labels found in {path}.")
            LOGGER.warning(f"{self.prefix}No labels found in {path}.")
        x["hash"] = self.get_cache_hash()
        x["results"] = nf, nm, ne, nc, total
        x["msgs"] = msgs
        if x["labels"]:
            save_dataset_cache_file(self.prefix, path, x, DATASET_CACHE_VERSION)
        return x

    # 2) 把 ThreadPool 换成串行假池（沙箱禁止命名管道，任何 Pool 都会 PermissionError）
    class _SerialPool:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def imap(self, func=None, iterable=None, **kw):
            func = func or kw.get("func")
            iterable = iterable if iterable is not None else kw.get("iterable")
            return (func(x) for x in iterable)

        def map(self, func, iterable):
            return [func(x) for x in iterable]

        def terminate(self):
            pass

        def join(self):
            pass

    import ultralytics.data.base as _base
    _patched = []
    for mod in (ds, _base):
        if hasattr(mod, "ThreadPool"):
            mod.ThreadPool = _SerialPool
            _patched.append(mod.__name__)
    print("[ultra_patch] ThreadPool 已串行化: %s" % ", ".join(_patched))

    ds.YOLODataset.cache_labels = serial_cache_labels
    print("[ultra_patch] 已把 YOLODataset.cache_labels 换成串行版（规避命名管道）")
    return True


if __name__ == "__main__":
    apply()
