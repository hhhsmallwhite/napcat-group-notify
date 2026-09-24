"""二维码自动刷新 + 登录状态面板。

QQ 登录二维码有效期只有两三分钟，而且 NapCat 刷新几次后就不再自己生成新码。
本面板通过 NapCat WebUI 的 /api/QQLogin/RefreshQRcode 主动刷新：
  * 显示当前二维码（从 <shell>/cache/qrcode.png 读，自动放大补白边）
  * 每 2 秒汇报登录阶段（waiting_qrcode / qrcode_scanned / ...）
  * 检测到二维码快过期就自动刷新，不会出现「扫了才发现已过期」

用法:
    python qr_server.py --shell D:/NapCat/shell     # 默认 127.0.0.1:8899
    python qr_server.py --shell D:/NapCat/shell 9000

依赖: pip install Pillow
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

SCALE = 8
MARGIN = 60
AUTO_REFRESH_AFTER = 100  # 秒；超过这个时长主动刷新二维码

PHASE_TEXT = {
    "waiting_qrcode": ("等待扫码", "#854F0B"),
    "qrcode_scanned": ("已扫码，请在手机上点「确认登录」", "#185FA5"),
    "waiting_login": ("正在登录…", "#185FA5"),
    "login_success": ("登录成功", "#0F6E56"),
    "": ("—", "#5F5E5A"),
}

_state = {"last_refresh": 0.0, "auto": 0}


class NapCat:
    def __init__(self, shell_dir: Path):
        cfg_path = shell_dir / "config" / "webui.json"
        if not cfg_path.exists():
            raise SystemExit(f"[!] 找不到 {cfg_path}")
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.base = f"http://127.0.0.1:{cfg.get('port', 6099)}"
        self.token = cfg["token"]
        self.qr_src = shell_dir / "cache" / "qrcode.png"
        self.cred: str | None = None
        self.lock = threading.Lock()

    def _call(self, path: str, payload=None, method="POST", _retry=True):
        with self.lock:
            if self.cred is None and _retry:
                h = hashlib.sha256((self.token + ".napcat").encode()).hexdigest()
                r = self._raw("/api/auth/login", {"hash": h, "totpCode": ""}, "POST", None)
                if r.get("code") == 0:
                    self.cred = r["data"]["Credential"]
            return self._raw(f"/api{path}", payload, method, self.cred)

    def _raw(self, path, payload, method, cred):
        headers = {"Content-Type": "application/json"}
        if cred:
            headers["Authorization"] = f"Bearer {cred}"
        data = (json.dumps(payload).encode() if payload is not None
                else (b"{}" if method == "POST" else None))
        req = urllib.request.Request(self.base + path, data=data, headers=headers,
                                     method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            return {"code": -1, "message": str(e)[:120]}

    def status(self):
        r = self._call("/QQLogin/CheckLoginStatus")
        return r.get("data") or {}

    def refresh(self):
        r = self._call("/QQLogin/RefreshQRcode")
        if r.get("code") == 0:
            _state["last_refresh"] = time.time()
            _state["auto"] += 1
        return r


def render_qr(qr_src: Path) -> bytes:
    src = Image.open(qr_src).convert("RGB")
    big = src.resize((src.width * SCALE, src.height * SCALE), Image.NEAREST)
    canvas = Image.new("RGB", (big.width + MARGIN * 2, big.height + MARGIN * 2), "white")
    canvas.paste(big, (MARGIN, MARGIN))
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>NapCat 登录</title>
<style>
  html,body{margin:0;height:100%;background:#f5f5f4;color:#2c2c2a;
    font-family:system-ui,-apple-system,"Microsoft YaHei",sans-serif;}
  .wrap{display:flex;flex-direction:column;align-items:center;justify-content:center;
    height:100%;gap:14px;}
  h1{font-size:16px;font-weight:500;margin:0;}
  img{width:min(56vh,56vw);image-rendering:pixelated;border:1px solid #d3d1c7;
    border-radius:12px;background:#fff;}
  .phase{font-size:15px;font-weight:500;}
  .meta{font-size:12px;color:#5f5e5a;line-height:1.7;text-align:center;}
  button{font:inherit;font-size:13px;padding:6px 14px;border-radius:8px;
    border:1px solid #b4b2a9;background:#fff;color:#2c2c2a;cursor:pointer;}
</style>
</head>
<body>
<div class="wrap">
  <h1>用要登录的 QQ（手机端）扫码</h1>
  <img id="qr" src="/qr.png" alt="登录二维码">
  <div class="phase" id="phase">读取中…</div>
  <div class="meta" id="meta"></div>
  <button onclick="doRefresh()">手动刷新二维码</button>
</div>
<script>
var lastMtime = 0;
function tick(){
  fetch('/state', {cache:'no-store'}).then(function(r){return r.json();}).then(function(d){
    if (d.mtime && d.mtime !== lastMtime) {
      lastMtime = d.mtime;
      document.getElementById('qr').src = '/qr.png?t=' + Date.now();
    }
    var p = document.getElementById('phase');
    p.textContent = d.phase_text;
    p.style.color = d.phase_color;
    document.getElementById('meta').innerHTML =
      '二维码生成于 ' + d.time + '，已过 ' + Math.round(d.age) + ' 秒'
      + (d.auto ? '<br>已自动刷新 ' + d.auto + ' 次' : '')
      + '<br>isLogin=' + d.isLogin + '  coreReady=' + d.coreReady;
  }).catch(function(){ document.getElementById('phase').textContent = '连接中断'; });
}
function doRefresh(){ fetch('/refresh', {method:'POST'}).then(tick); }
tick();
setInterval(tick, 2000);
</script>
</body>
</html>
"""


def build_handler(bot: NapCat):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path.split("?")[0] == "/refresh":
                bot.refresh()
                self._send(200, "application/json", b'{"ok":true}')
                return
            self._send(404, "text/plain", b"not found")

        def do_GET(self):
            path = self.path.split("?")[0]

            if path == "/":
                self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
                return

            if path == "/qr.png":
                if not bot.qr_src.exists():
                    self._send(404, "text/plain", b"no qrcode.png")
                    return
                try:
                    self._send(200, "image/png", render_qr(bot.qr_src))
                except Exception as e:  # noqa: BLE001
                    self._send(500, "text/plain", str(e).encode())
                return

            if path == "/state":
                st = bot.status()
                age = 0.0
                tstr = "-"
                mtime = 0
                if bot.qr_src.exists():
                    s = bot.qr_src.stat()
                    age = time.time() - s.st_mtime
                    tstr = time.strftime("%H:%M:%S", time.localtime(s.st_mtime))
                    mtime = int(s.st_mtime * 1000)

                phase = st.get("loginPhase", "")
                text, color = PHASE_TEXT.get(phase, (phase or "—", "#5F5E5A"))

                if st.get("isLogin"):
                    text, color = "登录成功", "#0F6E56"
                elif st.get("loginError"):
                    text, color = "出错：" + str(st["loginError"])[:80], "#A32D2D"

                # 快过期就自动刷新
                if not st.get("isLogin") and age > AUTO_REFRESH_AFTER:
                    bot.refresh()
                    text = "二维码已过期，正在自动刷新…"

                body = json.dumps({
                    "mtime": mtime, "age": age, "time": tstr,
                    "phase": phase, "phase_text": text, "phase_color": color,
                    "isLogin": bool(st.get("isLogin")),
                    "coreReady": bool(st.get("coreReady")),
                    "auto": _state["auto"],
                }, ensure_ascii=False).encode("utf-8")
                self._send(200, "application/json", body)
                return

            self._send(404, "text/plain", b"not found")

    return Handler


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shell", required=True, help="NapCat Shell 目录")
    ap.add_argument("port", nargs="?", type=int, default=8899)
    args = ap.parse_args()

    bot = NapCat(Path(args.shell))
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), build_handler(bot))
    print(f"[i] 面板地址: http://127.0.0.1:{args.port}")
    print(f"[i] 二维码源: {bot.qr_src}")
    print(f"[i] 超过 {AUTO_REFRESH_AFTER} 秒自动刷新二维码")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[i] 已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
