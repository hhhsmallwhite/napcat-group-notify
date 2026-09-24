"""统一配置加载。

所有个性化参数（群号、QQ 号、消息文本、路径）都放在 config.json，
代码仓库内不含任何真实账号信息。用法：

    from config import load_config
    cfg = load_config()               # 读仓库根目录的 config.json
    cfg = load_config("my.json")      # 或指定路径
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | None = None) -> dict:
    p = Path(path) if path else ROOT / "config.json"
    if not p.exists():
        raise SystemExit(
            f"[!] 配置文件不存在: {p}\n"
            "    请复制 config.example.json 为 config.json 并按注释填写。"
        )
    cfg = json.loads(p.read_text(encoding="utf-8"))
    missing = [
        k for k in ("napcat_shell", "ob11_http", "group_id", "test_user_id", "message")
        if k not in cfg
    ]
    if missing:
        raise SystemExit(f"[!] config.json 缺少必填项: {', '.join(missing)}")
    return cfg
