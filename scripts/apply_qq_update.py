"""把 QQ NT 增量热更新包应用到 QQ 目录的一份副本上。

适用场景：NapCat 对 QQ 版本是精确白名单（如 9.9.33-52230），而用户当前版本
不在名单里；旧版安装包被腾讯下架、命令行下载新版被反爬拦截时，可以从
QQ 自身的 `versions/<旧版>-<新版>.zip` 热更新包入手——QQ 经常已经把它
下载好了但从未应用（versions/config.json 里 readyVersion 为空即是信号）。

补丁包结构：
  diff.json          # {"added": {...}, "deleted": {...}, "modified": {...}}
                     #   每项含 {"size": int, "md5": str} 用于校验
  raw_files/...      # 新增文件的完整内容（部分 modified 文件也直接给整份）
  <路径/.→_>.patch   # modified 文件的 BSDIFF40 补丁，文件名=原路径 / 换 _ 加 .patch

安全原则：全程只操作副本，源 QQ 目录只读。每个产物都与 diff.json 的 size/md5
比对，任何一项对不上立即报错停止。

用法:
    python apply_qq_update.py --zip QQ热更新包.zip --src 当前QQ目录 --dst 目标副本目录
    python apply_qq_update.py --zip ... --src ... --dst ... --test   # 只验证补丁格式

依赖: pip install numpy
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bspatch import bspatch  # noqa: E402


def md5_of(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def load_diff(zf: zipfile.ZipFile) -> dict:
    return json.loads(zf.read("diff.json").decode("utf-8"))


def patch_name(path: str) -> str:
    return path.replace("/", "_") + ".patch"


def apply_one(zf: zipfile.ZipFile, diff: dict, path: str, src: Path, dst: Path) -> str:
    """处理单个 modified 文件，返回 'bsdiff' / 'raw'。"""
    info = diff["modified"][path]
    dst_file = dst / path
    dst_file.parent.mkdir(parents=True, exist_ok=True)

    cand = patch_name(path)
    if cand in zf.namelist():
        old_file = src / "versions" / path
        if not old_file.exists():
            # 有的版本目录结构与 src 布局不同，尝试 src 直下
            old_file = src / path
        old = old_file.read_bytes()
        new = bspatch(old, zf.read(cand))
        mode = "bsdiff"
    elif ("raw_files/" + path) in zf.namelist():
        new = zf.read("raw_files/" + path)
        mode = "raw"
    else:
        raise RuntimeError(f"{path}: 既无补丁也无整份文件")

    if len(new) != info["size"] or md5_of(new) != info["md5"]:
        raise RuntimeError(
            f"{path}: 校验失败 size({len(new)}/{info['size']}) md5({md5_of(new)}/{info['md5']})")
    dst_file.write_bytes(new)
    return mode


def cmd_test(zf: zipfile.ZipFile, diff: dict, src: Path) -> int:
    """取 modified 里最小的一个文件验证 bspatch 实现正确性。"""
    target = min(diff["modified"], key=lambda k: diff["modified"][k]["size"])
    info = diff["modified"][target]
    print(f"验证目标: {target} (期望 {info['size']:,} bytes)")

    old_file = src / "versions" / target
    if not old_file.exists():
        old_file = src / target
    new = bspatch(old_file.read_bytes(), zf.read(patch_name(target)))

    ok = len(new) == info["size"] and md5_of(new) == info["md5"]
    print(f"实际 {len(new):,} bytes, md5={md5_of(new)}")
    print(">>>", "PASS" if ok else "FAIL — bspatch 实现有问题")
    return 0 if ok else 1


def cmd_apply(zf: zipfile.ZipFile, diff: dict, src: Path, dst: Path) -> int:
    if dst.exists():
        raise SystemExit(f"[!] 目标已存在，拒绝覆盖: {dst}\n    删除后重试，或换一个目录。")
    print(f"[i] 复制 {src} -> {dst} （2~3 GB，耐心等）")
    t0 = time.time()
    shutil.copytree(src, dst)
    print(f"[i] 复制完成，{time.time() - t0:.0f} 秒")

    stats = {"added": 0, "bsdiff": 0, "raw": 0, "deleted": 0}
    total = len(diff.get("added", {})) + len(diff.get("modified", {}))

    for i, path in enumerate(diff.get("added", {}), 1):
        src_f = zf.read("raw_files/" + path)
        info = diff["added"][path]
        if len(src_f) != info["size"] or md5_of(src_f) != info["md5"]:
            raise RuntimeError(f"added {path}: 校验失败")
        dst_f = dst / path
        dst_f.parent.mkdir(parents=True, exist_ok=True)
        dst_f.write_bytes(src_f)
        stats["added"] += 1
        if i % 5 == 0 or i == total:
            print(f"  [{i}/{total}] added {path}")

    for i, path in enumerate(diff.get("modified", {}), 1):
        mode = apply_one(zf, diff, path, src, dst)
        stats[mode] += 1
        if i % 5 == 0 or i == total:
            print(f"  [{i}/{total}] {mode} {path}")

    for path in diff.get("deleted", {}):
        f = dst / path
        if f.exists():
            f.unlink()
        stats["deleted"] += 1

    print("\n=== 完成 ===")
    print(stats)
    print("验证方法：查看副本 versions/ 下的新版本目录，或启动后看 About 版本号。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True, help="热更新包路径（versions/旧版-新版.zip）")
    ap.add_argument("--src", required=True, help="当前 QQ 安装目录（只读，不会被改）")
    ap.add_argument("--dst", required=True, help="目标副本目录（会自动创建）")
    ap.add_argument("--test", action="store_true", help="只验证补丁格式，不落盘")
    args = ap.parse_args()

    src, dst = Path(args.src), Path(args.dst)
    if not src.exists():
        raise SystemExit(f"[!] 源目录不存在: {src}")

    zf = zipfile.ZipFile(args.zip)
    diff = load_diff(zf)
    print(f"补丁规模: added={len(diff.get('added', {}))} "
          f"modified={len(diff.get('modified', {}))} "
          f"deleted={len(diff.get('deleted', {}))}\n")

    if args.test:
        return cmd_test(zf, diff, src)
    return cmd_apply(zf, diff, src, dst)


if __name__ == "__main__":
    sys.exit(main())
