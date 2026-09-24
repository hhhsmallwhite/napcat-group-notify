"""bspatch 自测：不依赖外部数据，构造最小合法 BSDIFF40 补丁验证实现。

BSDIFF40 格式：
  header : "BSDIFF40" + ctrl_len + diff_len + new_size  (各 8 字节 signed-magnitude LE)
  ctrl   : bz2 压缩，每 24 字节一条 (x=diff段长, y=extra段长, z=old跳过量)
  diff   : bz2 压缩
  extra  : bz2 压缩
  new[x段] = diff[x段] + old[对应区间]（字节加法）；new[y段] = extra 原样拷贝

运行: python tests/test_bspatch.py
"""

from __future__ import annotations

import bz2
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from bspatch import bspatch, offtin  # noqa: E402


def enc(v: int) -> bytes:
    """signed-magnitude 小端编码（offtin 的逆运算）。"""
    neg = v < 0
    v = abs(v)
    b = bytearray(8)
    for i in range(8):
        b[i] = v & 0xFF
        v >>= 8
    if neg:
        b[7] |= 0x80
    return bytes(b)


def make_patch(ctrl_entries: list[tuple[int, int, int]],
               diff: bytes, extra: bytes, new_size: int) -> bytes:
    ctrl = b"".join(enc(x) + enc(y) + enc(z) for x, y, z in ctrl_entries)
    header = b"BSDIFF40" + enc(len(bz2.compress(ctrl))) + enc(len(bz2.compress(diff))) + enc(new_size)
    return header + bz2.compress(ctrl) + bz2.compress(diff) + bz2.compress(extra)


def test_offtin_roundtrip() -> None:
    for v in (0, 1, 255, 256, 65535, -1, -256, 2**31, -(2**31)):
        assert offtin(enc(v), 0) == v, v
    print("offtin roundtrip ok")


def test_extra_only() -> None:
    """纯新增内容：x=0, y=len(payload), z=0。"""
    payload = b"Hello, bsdiff!"
    patch = make_patch([(0, len(payload), 0)], b"", payload, len(payload))
    out = bspatch(b"", patch)
    assert out == payload, (out, payload)
    print("extra-only patch ok")


def test_diff_add() -> None:
    """diff 段与 old 逐字节相加：new = old + diff（模 256）。"""
    old = bytes([10, 20, 30, 40])
    delta = bytes([1, 2, 3, 4])          # 期望结果 11, 22, 33, 44
    expected = bytes([11, 22, 33, 44])
    patch = make_patch([(4, 0, 0)], delta, b"", len(expected))
    out = bspatch(old, patch)
    assert out == expected, (out, expected)
    print("diff-add patch ok")


def test_wraparound() -> None:
    """字节加法应模 256 回绕。"""
    old = bytes([250, 250])
    delta = bytes([10, 0])
    patch = make_patch([(2, 0, 0)], delta, b"", 2)
    out = bspatch(old, patch)
    assert out == bytes([4, 250]), list(out)
    print("wraparound ok")


def test_mixed_segments() -> None:
    """x + y + z 混合：先叠加 old、再插新内容、再跳过 old。"""
    old = bytes([1, 2, 3, 4, 5, 6])
    delta = bytes([1, 1, 1])              # 三段 diff 各 +1
    extra = b"XYZ"
    # (x=2, y=3, z=2)：new[0:2] = diff[0:2] + old[0:2] = [2, 3]
    #                   new[2:5] = extra = "XYZ"
    #                   oldpos 跳到 4
    # (x=1, y=0, z=0)：new[5] = diff[2] + old[4] = 1 + 5 = 6
    expected = bytes([2, 3]) + b"XYZ" + bytes([6])
    patch = make_patch([(2, 3, 2), (1, 0, 0)], delta, extra, len(expected))
    out = bspatch(old, patch)
    assert out == expected, (list(out), list(expected))
    print("mixed segments ok")


def test_bad_magic() -> None:
    try:
        bspatch(b"", b"NOTBSDIFF" + b"\x00" * 32)
    except ValueError:
        print("bad-magic rejection ok")
        return
    raise AssertionError("应当拒绝非 BSDIFF40 数据")


if __name__ == "__main__":
    test_offtin_roundtrip()
    test_extra_only()
    test_diff_add()
    test_wraparound()
    test_mixed_segments()
    test_bad_magic()
    print("\n>>> all bspatch self-tests PASS")
