"""按名单逐个发送群临时会话消息。

背景：目标账号在目标群里，但名单上的人通常不是它的好友，
所以走 OneBot 11 的「群临时会话」：send_msg + message_type=private + group_id。
（对非好友私聊必须带 group_id，表示从该群的临时会话入口发送。）

安全设计（都别去掉）：
  * 随机间隔（默认 20-40 秒）——固定/过短间隔是机器人典型特征，最容易触发风控
  * 纯文字——群临时会话发图片必失败，链接/文件是风控重灾区
  * 逐条落盘结果；连续失败达阈值立即停止，不重试不硬闯
  * --test 先给自己人发一条，人工确认收到后再发正式名单
  * 发送前 --list 展示完整清单

用法:
    python send_messages.py --list     # 只显示将要发送的清单，不发
    python send_messages.py --test     # 测试：只发给 test_user_id 1 条
    python send_messages.py --go       # 正式发送
    python send_messages.py --go --min-gap 25 --max-gap 45
    python send_messages.py --go --config my.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import load_config, ROOT  # noqa: E402

HERE = Path(__file__).parent
RESULT_FILE = HERE / "send_result.json"


def api(ob: str, action: str, **params):
    req = urllib.request.Request(
        ob + "/" + action,
        data=json.dumps(params).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode("utf-8"))
    if d.get("status") != "ok":
        raise RuntimeError(f"{action} 失败: {d.get('message')} | wording={d.get('wording')}")
    return d.get("data")


def load_targets(cfg: dict) -> list[dict]:
    """名单 ∩ 群名片 精确匹配 + 人工确认的别名表，按 QQ 号去重。"""
    names_path = ROOT / cfg.get("names_file", "names.txt")
    names = [l.strip() for l in names_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    ns = set(names)

    members = api(cfg["ob11_http"], "get_group_member_list",
                  group_id=cfg["group_id"], no_cache=True)
    by_card: dict[str, dict] = {}
    for m in members:
        c = (m.get("card") or "").strip()
        if c and c not in by_card:
            by_card[c] = m

    out = []
    for n in names:
        m = by_card.get(n)
        if m and m["user_id"] != cfg["test_user_id"]:
            out.append({"name": n, "user_id": m["user_id"], "card": m.get("card")})

    # 人工确认过的「同名不同字」别名（名单写法 → 真实 QQ 号）
    have = {t["user_id"] for t in out}
    for item in cfg.get("alias", []):
        uid = int(item["user_id"])
        if uid in have:
            continue
        m = next((x for x in members if x["user_id"] == uid), None)
        if m:
            out.append({"name": item["name"], "user_id": uid, "card": m.get("card")})

    # 同一 QQ 只发一次
    seen: set[int] = set()
    uniq = []
    for t in out:
        if t["user_id"] in seen:
            continue
        seen.add(t["user_id"])
        uniq.append(t)
    uniq.sort(key=lambda x: x["user_id"])
    return uniq


def send_private(ob: str, user_id: int, group_id: int, text: str) -> dict:
    """群临时会话：message_type=private 且带 group_id。"""
    return api(ob, "send_msg",
               message_type="private", user_id=user_id,
               group_id=group_id, message=text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--config", help="配置文件路径（默认仓库根目录 config.json）")
    ap.add_argument("--min-gap", type=int)
    ap.add_argument("--max-gap", type=int)
    args = ap.parse_args()

    cfg = load_config(args.config)
    min_gap = args.min_gap or cfg.get("min_gap_sec", 20)
    max_gap = args.max_gap or cfg.get("max_gap_sec", 40)
    max_fail = cfg.get("max_consecutive_fail", 3)

    targets = load_targets(cfg)

    if args.list:
        print(f"将要发送 {len(targets)} 人，内容：\n  {cfg['message']}\n")
        for i, t in enumerate(targets, 1):
            print(f"%2d  %-8s  QQ=%s" % (i, t["name"], t["user_id"]))
        print(f"\n间隔：{min_gap}~{max_gap} 秒随机")
        return 0

    if args.test:
        print(f"[test] 向 test_user_id={cfg['test_user_id']} 发送 1 条，验证群临时会话通路…")
        try:
            r = send_private(cfg["ob11_http"], cfg["test_user_id"],
                             cfg["group_id"], cfg["message"])
            print("[test] 成功！message_id =", r.get("message_id"))
            print("       请到接收号上确认收到后，再执行 --go。")
            return 0
        except Exception as e:  # noqa: BLE001
            print("[test] 失败：", e)
            print("       「群临时会话」通路不通（检查账号是否在群内、群是否开放临时会话）。")
            return 1

    if not args.go:
        ap.print_help()
        return 2

    print(f"[i] 开始发送，共 {len(targets)} 人")
    print(f"[i] 间隔 {min_gap}~{max_gap} 秒；连续失败 {max_fail} 次即停")
    print(f"[i] 内容：{cfg['message']}\n")

    results = []
    consec_fail = 0
    for i, t in enumerate(targets, 1):
        ts = datetime.now().strftime("%H:%M:%S")
        try:
            r = send_private(cfg["ob11_http"], t["user_id"], cfg["group_id"], cfg["message"])
            results.append({"name": t["name"], "user_id": t["user_id"],
                            "ok": True, "mid": r.get("message_id")})
            print(f"{ts}  [{i}/{len(targets)}] OK  {t['name']} ({t['user_id']})")
            consec_fail = 0
        except Exception as e:  # noqa: BLE001
            results.append({"name": t["name"], "user_id": t["user_id"],
                            "ok": False, "err": str(e)[:200]})
            consec_fail += 1
            print(f"{ts}  [{i}/{len(targets)}] FAIL  {t['name']} ({t['user_id']}) -> {str(e)[:120]}")
            if consec_fail >= max_fail:
                print(f"\n[!] 连续 {consec_fail} 条失败，立即停止。"
                      f"剩下的 {len(targets) - i} 人未发送。")
                break

        RESULT_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                               encoding="utf-8")

        if i < len(targets):
            gap = random.randint(min_gap, max_gap)
            print(f"      等 {gap} 秒…")
            time.sleep(gap)

    ok = sum(1 for r in results if r["ok"])
    print(f"\n[i] 完成：成功 {ok} / 失败 {len(results) - ok} / 共尝试 {len(results)}")
    RESULT_FILE.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print(f"[i] 结果已写入 {RESULT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
