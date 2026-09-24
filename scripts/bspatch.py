"""纯 Python 实现的 bsdiff bspatch（BSDIFF40）。

QQ NT 的热更新包用的就是标准 bsdiff：
  header : "BSDIFF40" + ctrl_len + diff_len + new_size   (各 8 字节，signed-magnitude LE)
  ctrl   : bz2 压缩
  diff   : bz2 压缩
  extra  : bz2 压缩

注意两个坑：
  * 头部三个长度字段是 signed-magnitude 编码（最高字节 bit7 为符号位），
    不是普通补码整数
  * ctrl_len 等是**压缩后**长度，所以会出现 57 这种不是 24 倍数的怪数字

官方 bsdiff4 库在部分 Python 版本下没有可用 wheel，故自行实现；
字节加法用 numpy 向量化，12MB 文件 0.04 秒可完成。

依赖: pip install numpy
"""

from __future__ import annotations

import bz2

import numpy as np

MAGIC = b"BSDIFF40"


def offtin(buf: bytes, off: int) -> int:
    """bsdiff 的 off_t 编码：signed-magnitude，little-endian，最高位是符号。"""
    y = buf[off + 7] & 0x7F
    for i in range(6, -1, -1):
        y = (y << 8) | buf[off + i]
    return -y if (buf[off + 7] & 0x80) else y


def bspatch(old: bytes, patch: bytes) -> bytes:
    """把 patch 应用到 old 上，返回新内容。"""
    if patch[:8] != MAGIC:
        raise ValueError(f"不是 BSDIFF40 补丁（前 8 字节={patch[:8]!r}）")

    ctrl_len = offtin(patch, 8)
    diff_len = offtin(patch, 16)
    new_size = offtin(patch, 24)

    pos = 32
    ctrl = bz2.decompress(patch[pos : pos + ctrl_len])
    pos += ctrl_len
    diff = bz2.decompress(patch[pos : pos + diff_len])
    pos += diff_len
    extra = bz2.decompress(patch[pos:])

    new = bytearray(new_size)
    new_arr = np.frombuffer(new, dtype=np.uint8)  # 可写视图，直接改 new
    oldlen = len(old)

    oldpos = newpos = cpos = dpos = epos = 0

    while newpos < new_size:
        x = offtin(ctrl, cpos)
        cpos += 8
        y = offtin(ctrl, cpos)
        cpos += 8
        z = offtin(ctrl, cpos)
        cpos += 8

        if newpos + x > new_size:
            raise ValueError("补丁损坏：diff 段越界")
        if newpos + x + y > new_size:
            raise ValueError("补丁损坏：extra 段越界")

        # 1) 把 diff 段原样写入
        if x:
            new[newpos : newpos + x] = diff[dpos : dpos + x]
            dpos += x

            # 2) 叠加 old 中对应区间的字节（重叠部分才需要）
            lo = max(0, -oldpos)
            hi = min(x, oldlen - oldpos)
            if hi > lo:
                n = hi - lo
                ov = np.frombuffer(old, dtype=np.uint8, count=n, offset=oldpos + lo)
                base = newpos + lo
                new_arr[base : base + n] = new_arr[base : base + n] + ov

            newpos += x
            oldpos += x

        # 3) extra 段（纯新增内容）
        if y:
            new[newpos : newpos + y] = extra[epos : epos + y]
            epos += y
            newpos += y

        # 4) 跳过 old 中的一段
        oldpos += z

    return bytes(new)
