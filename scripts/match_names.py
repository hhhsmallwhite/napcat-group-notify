"""名单 ↔ 群成员匹配。

把 names.txt（一行一个姓名）与目标群的群名片做精确匹配，输出三档结果：
  * 精确命中  —— 名单姓名 == 群名片，可直接发送
  * 名单未命中 —— 名单上有、群里找不到（含「疑似 OCR 错字」提示）
  * 群内多出   —— 群里有群名片、但名单上没有

发布前必读：名单通常来自截图 OCR，形近字错误率不低（实测 109 人错 3 处）。
存疑的名字请把原图对应单元格放大后逐字核对，别直接信 OCR。

用法:
    python match_names.py                    # 按名单匹配
    python match_names.py --list-groups      # 列出账号所在全部群（找 group_id 用）
    python match_names.py --config my.json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import load_config, ROOT  # noqa: E402

HERE = Path(__file__).parent
RESULT_FILE = HERE / "match_result.json"


def api(ob: str, action: str, **params):
    req = urllib.request.Request(
        ob + "/" + action,
        data=json.dumps(params).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=40) as r:
        d = json.loads(r.read().decode("utf-8"))
    if d.get("status") != "ok":
        raise RuntimeError(f"{action} 失败: {d.get('message')} | wording={d.get('wording')}")
    return d.get("data")


def list_groups(cfg: dict) -> int:
    groups = api(cfg["ob11_http"], "get_group_list")
    print(f"账号共在 {len(groups)} 个群：\n")
    for g in sorted(groups, key=lambda x: x["group_id"]):
        print(f"  {g['group_id']:<12} {g['group_name']}")
    return 0


def lev1(a: str, b: str) -> bool:
    """编辑距离是否 <= 1（用于提示疑似 OCR 错字，只提示不自动发）。"""
    if abs(len(a) - len(b)) > 1:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] <= 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-groups", action="store_true")
    ap.add_argument("--config")
    args = ap.parse_args()

    cfg = load_config(args.config)

    if args.list_groups:
        return list_groups(cfg)

    names_path = ROOT / cfg.get("names_file", "names.txt")
    names = [l.strip() for l in names_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    ns = set(names)

    members = api(cfg["ob11_http"], "get_group_member_list",
                  group_id=cfg["group_id"], no_cache=True)
    try:
        friends = {f["user_id"] for f in api(cfg["ob11_http"], "get_friend_list")}
    except RuntimeError:
        friends = set()

    by_card: dict[str, list[dict]] = {}
    for m in members:
        c = (m.get("card") or "").strip()
        if c:
            by_card.setdefault(c, []).append(m)

    hit, seen = [], set()
    for n in names:
        for m in by_card.get(n, []):
            if m["user_id"] in seen:
                continue
            seen.add(m["user_id"])
            hit.append({"name": n, "user_id": m["user_id"], "card": m.get("card"),
                        "is_friend": m["user_id"] in friends})

    unmatched = [n for n in names if n not in by_card]
    extra = sorted(set(by_card) - ns)

    # 疑似 OCR 错字：名单未命中项与群名片编辑距离<=1 的组合，只提示、需人工裁决
    ocr_suspects = []
    for n in unmatched:
        for c in by_card:
            if c not in ns and c != n and lev1(n, c) and not (len(n) == 2 and len(c) == 2):
                ocr_suspects.append({"list_name": n, "group_card": c})

    result = {
        "list_count": len(names),
        "group_member_count": len(members),
        "matched": hit,
        "unmatched": unmatched,
        "in_group_but_not_in_list": extra,
        "ocr_suspects": ocr_suspects,
    }
    RESULT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    print(f"名单 {len(names)} 人 | 群 {len(members)} 人 | 精确命中 {len(hit)} 人\n")
    print("=== 命中（可直接进发送名单）===")
    for i, h in enumerate(hit, 1):
        print("%2d  %-8s QQ=%-12s 群名片=%s%s"
              % (i, h["name"], h["user_id"], h.get("card"),
                 "  [好友]" if h["is_friend"] else ""))
    if unmatched:
        print(f"\n=== 名单未命中 {len(unmatched)} 人 ===")
        print("  " + "、".join(unmatched))
    if ocr_suspects:
        print("\n=== 疑似 OCR 错字（人工核对后，确认是同一人再写进 config 的 alias）===")
        for s in ocr_suspects:
            print(f"  名单「{s['list_name']}」 ≈ 群名片「{s['group_card']}」")
    if extra:
        print(f"\n=== 群内但不在名单 {len(extra)} 人 ===")
        print("  " + "、".join(extra))
    print(f"\n[i] 结果已写入 {RESULT_FILE}")
    print("[i] 未命中/疑似错字/群内多出 三档都需要你人工裁决，不要自动扩大发送范围。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
