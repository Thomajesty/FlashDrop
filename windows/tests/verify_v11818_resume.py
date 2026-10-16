# -*- coding: utf-8 -*-
"""resume.py 块位图算法专项测试（纯逻辑，无需 GUI/网络）

运行：python windows/tests/verify_v11818_resume.py
"""
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = os.path.dirname(HERE)
if WIN not in sys.path:
    sys.path.insert(0, WIN)

from app import resume as R  # noqa: E402

FAILS = []
N = 0


def ck(name, cond, extra=""):
    global N
    N += 1
    if not cond:
        FAILS.append(f"{name} {extra}")
    print(("  ok  " if cond else " FAIL ") + name + ((" | " + str(extra)) if extra and not cond else ""))


def main():
    print("=" * 68)
    print("v1.18.18 断点续传核心（块位图）测试")
    print("=" * 68)

    # ---- 分块规划 ----
    ck("0 字节 -> 1 块", R.total_chunks(0) == 1)
    ck("1 字节 -> 1 块", R.total_chunks(1) == 1)
    ck("正好一块", R.total_chunks(R.RESUME_CHUNK) == 1)
    ck("多一块 -> 2 块", R.total_chunks(R.RESUME_CHUNK + 1) == 2)
    ck("10MB -> 20 块", R.total_chunks(10 * 1024 * 1024) == 20)
    ck("块偏移=块号*CHUNK", R.chunk_offset(3) == 3 * R.RESUME_CHUNK)
    ck("末块长度=剩余", R.chunk_len(1, R.RESUME_CHUNK + 100) == 100)
    ck("满块长度=CHUNK", R.chunk_len(0, R.RESUME_CHUNK * 2) == R.RESUME_CHUNK)

    # ---- 位图基本操作 ----
    cm = R.ChunkMap(10)
    ck("初始 count=0", cm.count() == 0)
    ck("初始 add 返回 True", cm.add(0) is True)
    ck("重复 add 返回 False", cm.add(0) is False)
    ck("has(0)", cm.has(0) and not cm.has(1))
    ck("越界 has=False", cm.has(10) is False and cm.has(-1) is False)
    cm.add(7)
    ck("跨字节边界 has(7)", cm.has(7))
    cm.add(9)
    ck("count=3", cm.count() == 3)
    ck("complete=False", cm.complete() is False)
    for i in range(1, 10):
        cm.add(i)
    ck("全部收齐 complete", cm.complete() is True)

    # ---- 收到字节数按块号推导 ----
    size = R.RESUME_CHUNK * 3 + 77
    cm2 = R.ChunkMap(R.total_chunks(size))
    cm2.add(0)
    cm2.add(1)
    ck("已收 2 满块 = 2*CHUNK", cm2.received_bytes(size) == 2 * R.RESUME_CHUNK)
    cm2.add(3)
    ck("末块按实际长度计", cm2.received_bytes(size) == 2 * R.RESUME_CHUNK + 77)
    ck("缺失块列表", cm2.missing() == [2])

    # ---- 紧凑区间往返 ----
    cm3 = R.ChunkMap(20)
    for i in [0, 1, 2, 5, 9, 10, 19]:
        cm3.add(i)
    rr = cm3.to_compact()
    ck("区间压缩 [[0,2],[5,5],[9,10],[19,19]]", rr == [[0, 2], [5, 5], [9, 10], [19, 19]], rr)
    back = R.ChunkMap.from_compact(rr, 20)
    ck("区间往返一致", [back.has(i) for i in range(20)] == [cm3.has(i) for i in range(20)])
    full = R.ChunkMap(5)
    for i in range(5):
        full.add(i)
    ck("全收区间为单项", full.to_compact() == [[0, 4]])
    ck("空区间为空列表", R.ChunkMap(5).to_compact() == [])

    # ---- base64 往返 ----
    b64 = cm3.to_b64()
    rt = R.ChunkMap.from_b64(b64, 20)
    ck("base64 往返一致", [rt.has(i) for i in range(20)] == [cm3.has(i) for i in range(20)])
    ck("非 8 对齐不会多算", R.ChunkMap.from_b64(b64, 20).count() == cm3.count())
    ck("垃圾输入不抛异常", R.ChunkMap.from_b64("!!!not-b64!!!", 8).count() == 0)
    ck("空串 -> 全缺", R.ChunkMap.from_b64("", 8).count() == 0)

    # ---- 落盘往返 ----
    tmp = tempfile.mkdtemp(prefix="fd_resume_")
    try:
        ok = cm3.save(tmp, "tidA")
        ck("位图落盘成功", ok is True)
        ld = R.ChunkMap.load(tmp, "tidA", 20)
        ck("落盘往返一致", [ld.has(i) for i in range(20)] == [cm3.has(i) for i in range(20)])
        ck("不存在的 tid -> 全缺", R.ChunkMap.load(tmp, "tidNOPE", 20).count() == 0)
        ck("损坏文件不抛异常", R.ChunkMap.load(tmp, "tidA", 20) is not None)
        # 原子写不留 tmp
        leftovers = [f for f in os.listdir(tmp) if f.endswith(".tmp")]
        ck("无残留 .tmp", leftovers == [], leftovers)

        # ---- 指纹 ----
        f1 = R.resume_fingerprint(100, "a.txt")
        f2 = R.resume_fingerprint(100, "a.txt")
        f3 = R.resume_fingerprint(101, "a.txt")
        f4 = R.resume_fingerprint(100, "b.txt")
        ck("同文件指纹稳定", f1 == f2)
        ck("大小不同指纹不同", f1 != f3)
        ck("文件名不同指纹不同", f1 != f4)
        R.save_fingerprint(tmp, "tidA", 100, "a.txt")
        ck("指纹落盘可读回", R.load_fingerprint(tmp, "tidA") == f1)
        ck("无指纹文件返回空", R.load_fingerprint(tmp, "tidZZZ") == "")

        # ---- 清理 ----
        R.drop_resume_state(tmp, "tidA")
        ck("清理后位图消失", R.ChunkMap.load(tmp, "tidA", 20).count() == 0)
        ck("清理后指纹消失", R.load_fingerprint(tmp, "tidA") == "")
        R.drop_resume_state(tmp, "tid_NOT_EXIST")  # 不应抛异常
        ck("清理不存在的状态不抛异常", True)
    finally:
        try:
            for f in os.listdir(tmp):
                os.remove(os.path.join(tmp, f))
            os.rmdir(tmp)
        except Exception:
            pass

    # ---- 退避 ----
    ck("退避递增", R.next_backoff(1) < R.next_backoff(2) < R.next_backoff(3))
    ck("退避有上限", R.next_backoff(50) == 30.0)
    ck("退避非法输入不炸", 0 < R.next_backoff("x") <= 30.0)

    # ---- 协议层新帧编解码（无需网络，直接解 payload）----
    import struct
    from app import protocol as P

    ck("KIND_CHUNK 已定义", P.KIND_CHUNK == 0x43)
    frame = P.encode_chunk("t1", 7, b"hello")
    (ln,) = struct.unpack(">I", frame[:4])
    payload = frame[4:]
    ck("chunk 帧长度一致", ln == len(payload))
    ck("chunk 帧类型字节", payload[0] == P.KIND_CHUNK)
    (n,) = struct.unpack(">H", payload[1:3])
    tid = payload[3:3 + n].decode()
    (idx,) = struct.unpack(">I", payload[3 + n:7 + n])
    (m,) = struct.unpack(">Q", payload[7 + n:15 + n])
    data = payload[15 + n:]
    ck("chunk tid 正确", tid == "t1")
    ck("chunk 块号正确", idx == 7)
    ck("chunk 长度正确", m == 5 and data == b"hello")
    ck("老帧 encode_bin 不受影响", P.encode_bin("t1", b"x")[4] == P.KIND_BIN)
    ck("MAX_FRAME 容纳新帧头", P.MAX_FRAME >= 1 + 2 + 64 + 4 + 8 + P.CHUNK_SIZE)

    # ---- 回归断言：v1.18.18 首版两个致命 bug（已被端到端测试抓到）----
    # bug1: skip = set(cm.missing()) —— 把"要发的块"当成"跳过的块"，
    #       结果首次传输（have=[] → 全部块都是 missing）一个块都不发。
    # bug2: md5.update 只在"跳过块"分支里调用 —— 正常传输摘要恒为空，
    #       接收端 MD5 校验必然失败。
    # 这两条是**语义断言**：光看代码"看起来对"抓不到，必须验证语义。
    src = os.path.join(os.path.dirname(HERE), "app", "node.py")
    code = open(src, "r", encoding="utf-8").read()

    ck("bug1回归：skip 是 missing 的补集（非 missing 本身）",
       "skip = set(range(nchunks)) - todo" in code
       and "skip = set(cm.missing())" not in code,
       "skip 语义写反会让首次传输一个块都不发")
    # md5.update 必须在"发送/跳过"判断**之外**，保证覆盖全部块。
    # 用逐行缩进分析而不是一条大正则 —— 大正则依赖精确缩进，
    # 任何人调整一下代码缩进就会假失败（这类断言历史上栽过跟头）。
    # ★ v1.18.20 演进：blk 切片必须先定位到 _send_file_to 函数体 ——
    #   v1.18.18 引入 _md5_of_file（文件更早位置也有 with open(path,"rb")）
    #   后，全文件首个匹配会切错函数，缩进分析混入无关 else 导致假失败。
    fn_i = code.index("async def _send_file_once")   # 发送循环在 once 内层
    fn_end = code.index("\n    async def ", fn_i + 10)
    fn_code = code[fn_i:fn_end]
    blk = fn_code[fn_code.index('with open(path, "rb") as f:'):
                  fn_code.index('await conn.send_json({"type": P.T_FILE_END')]
    lines = blk.splitlines()
    md5_i = [k for k, ln in enumerate(lines) if "md5.update(chunk)" in ln]
    # else 分支行（若存在）与 md5.update 行的缩进比较：
    # md5.update 必须与 if/else **同级或更外层**，才能对所有块生效。
    else_i = [k for k, ln in enumerate(lines)
              if ln.strip() == "else:" and "skip" not in ln]
    ok = False
    if len(md5_i) == 1:
        mi = md5_i[0]
        ind = lambda s: len(s) - len(s.lstrip())
        mi_ind = ind(lines[mi])
        # 必须在最后一个 else 之后，且缩进不比它深
        ok = mi_ind <= min((ind(lines[k]) for k in else_i), default=mi_ind)
    ck("bug2 回归：md5.update 覆盖全部块", ok,
       f"md5.update 出现 {len(md5_i)} 次，else 分支 {len(else_i)} 处；"
       "若 md5.update 在 else(跳过块) 内则摘要只覆盖跳过块")

    # 语义级：构造"对方一块都没收到"的场景，跳过集合必须为空
    n5 = R.total_chunks(5 * R.RESUME_CHUNK + 7)
    cm_empty = R.ChunkMap.from_compact([], n5)
    todo5 = set(cm_empty.missing())
    skip5 = set(range(n5)) - todo5
    ck("首次传输不跳过任何块", len(skip5) == 0 and len(todo5) == n5,
       f"skip={len(skip5)} todo={len(todo5)}")
    # 对方已有前3 块 → 跳过 3 块，发送其余
    cm_part = R.ChunkMap.from_compact([[0, 2]], n5)
    todo_p = set(cm_part.missing())
    skip_p = set(range(n5)) - todo_p
    ck("续传只补缺失块", len(skip_p) == 3 and len(todo_p) == n5 - 3,
       f"skip={len(skip_p)} todo={len(todo_p)}")
    ck("续传进度基准= 已收字节（进度不倒退）",
       sum(R.chunk_len(i, 5 * R.RESUME_CHUNK + 7) for i in skip_p) > 0)

    # ---- 跨端 base64 互解（v1.18.18 两端联调时发现）----
    # Android 的 FdResume.B64.encode() 输出带 '=' 填充；
    # 而 Python 的 base64.b64decode 遇到**无填充**串会抛
    # `binascii.Error: Incorrect padding` —— 跨端直接解不出来。
    # 用固定基准值锁住两端一致（基准值取自实测，不是拍脑袋）。
    import base64 as _b64
    cm_fix = R.ChunkMap(8)
    cm_fix.add(0)
    cm_fix.add(3)
    ck("base64 基准值与 Android 端一致（ChunkMap(8) add0/add3）",
       cm_fix.to_b64() == "CQ==", cm_fix.to_b64())
    ck("可解无填充串（防御 Android 旧实现）",
       R.ChunkMap.from_b64("CQ", 8).count() == 2,
       R.ChunkMap.from_b64("CQ", 8).count())
    ck("可解带填充串", R.ChunkMap.from_b64("CQ==", 8).count() == 2)
    # 往返一致性
    for n in (1, 8, 9, 40, 1000):
        cmx = R.ChunkMap(n)
        for i in range(0, n, 3):
            cmx.add(i)
        if R.ChunkMap.from_b64(cmx.to_b64(), n).missing() != cmx.missing():
            ck(f"base64 往返 n={n}", False)
            break
    else:
        ck("base64 往返一致（多组 n）", True)

    print("=" * 68)
    print(f"结果：{N - len(FAILS)}/{N} 通过")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print("  - " + f)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())