"""NapCat WebUI API 客户端。

在不打开浏览器的情况下读取/修改 NapCat 的登录状态与 OneBot 配置。
NapCat (https://github.com/NapNeko/NapCatQQ) 是 OneBot 11 协议端，
其 WebUI 没有官方 API 文档，本模块的认证与接口是从前端 JS 逆向所得：

    1. 读 <shell>/config/webui.json 里的 token
    2. hash = SHA256(token + ".napcat")
    3. POST /api/auth/login  {"hash": hash, "totpCode": ""}   → data.Credential
    4. 后续所有请求带 Authorization: Bearer <Credential>
    5. 全部 API 一律 POST（GET 一律 404 "Cannot GET"）

用法:
    python napcat_webui.py status          # 登录状态 + 快速登录列表
    python napcat_webui.py ob11            # 打印 OneBot 配置
    python napcat_webui.py enable-http     # 启用 OneBot HTTP（127.0.0.1:3000）

shell 目录来源（按优先级）: --shell 参数 > config.json 的 napcat_shell
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import load_config  # noqa: E402


class NapCatWebUI:
    def __init__(self, shell_dir: str | Path):
        self.shell = Path(shell_dir)
        cfg_path = self.shell / "config" / "webui.json"
        if not cfg_path.exists():
            raise SystemExit(f"[!] 找不到 {cfg_path} —— 请确认 NapCat Shell 目录是否正确")
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.base = f"http://127.0.0.1:{cfg.get('port', 6099)}".rstrip("/")
        self._token = cfg["token"]
        self._cred: str | None = None

    # ---------------------------------------------------------------- low level

    def _raw(self, path: str, payload=None, method: str = "POST", auth: str | None = None):
        # NapCat WebUI 的 API 全部用 POST（GET 一律 404 "Cannot GET ..."）
        url = f"{self.base}/api{path}"
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {auth}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{path} HTTP {e.code}: {e.read()[:200]!r}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"{path} 连不上 {self.base}：{e.reason}") from e

    def login(self) -> str:
        h = hashlib.sha256((self._token + ".napcat").encode()).hexdigest()
        resp = self._raw("/auth/login", {"hash": h, "totpCode": ""}, "POST")
        if resp.get("code") != 0:
            raise RuntimeError(f"WebUI 登录失败: {resp}")
        self._cred = resp["data"]["Credential"]
        return self._cred

    def call(self, path: str, payload=None, method: str = "POST"):
        if self._cred is None:
            self.login()
        resp = self._raw(path, payload, method, auth=self._cred)
        if resp.get("code") != 0:
            raise RuntimeError(f"{path} 返回错误: {resp.get('message')}")
        return resp.get("data")

    # ----------------------------------------------------------------- high level

    def login_info(self):
        """uid/uin/nick，未登录时全空。"""
        return self.call("/QQLogin/GetQQLoginInfo")

    def check_login_status(self):
        """isLogin / loginPhase / qrLoginAccepted / coreReady / loginError。"""
        return self.call("/QQLogin/CheckLoginStatus")

    def quick_login_list(self):
        return self.call("/QQLogin/GetQuickLoginList")

    def refresh_qrcode(self):
        """主动刷新登录二维码（更新 <shell>/cache/qrcode.png）。"""
        return self.call("/QQLogin/RefreshQRcode")

    def ob11_config(self):
        return self.call("/OB11Config/GetConfig")

    def set_ob11_config(self, cfg):
        # SetConfig 要求把配置整体序列化成 JSON 字符串再包一层，
        # 直接传对象会报 "config is empty"。
        return self.call("/OB11Config/SetConfig", {"config": json.dumps(cfg)}, "POST")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=["status", "ob11", "enable-http"])
    ap.add_argument("--shell", help="NapCat Shell 目录（默认读 config.json 的 napcat_shell）")
    args = ap.parse_args()

    shell = args.shell
    if not shell:
        try:
            shell = load_config()["napcat_shell"]
        except SystemExit:
            ap.error("未指定 --shell 且 config.json 不可用")

    ui = NapCatWebUI(shell)

    if args.action == "status":
        info = ui.login_info()
        print("=== 登录信息 ===")
        print(json.dumps(info, ensure_ascii=False, indent=2))
        st = ui.check_login_status()
        print("\n=== 登录状态机 ===")
        print(json.dumps(st, ensure_ascii=False, indent=2))
        try:
            ql = ui.quick_login_list()
            print("\n=== 快速登录列表 ===")
            print(json.dumps(ql, ensure_ascii=False, indent=2)[:800])
        except RuntimeError as e:
            print(f"\n=== 快速登录列表不可用: {e} ===")

    elif args.action == "ob11":
        print(json.dumps(ui.ob11_config(), ensure_ascii=False, indent=2))

    elif args.action == "enable-http":
        cfg = ui.ob11_config()
        servers = cfg.setdefault("network", {}).setdefault("httpServers", [])
        if servers:
            s = servers[0]
            s.update({"enable": True, "host": "127.0.0.1", "port": 3000})
        else:
            servers.append({
                "enable": True, "name": "napcat-http", "host": "127.0.0.1",
                "port": 3000, "enableCors": True, "enableWebsocket": False,
                "messagePostFormat": "array", "debug": False, "token": "",
            })
        ui.set_ob11_config(cfg)
        after = ui.ob11_config()
        print("httpServers =", json.dumps(after["network"]["httpServers"], ensure_ascii=False))
        print("提示: netstat 确认 3000 监听后，用 OneBot API get_login_info 验证。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
