# -*- coding: utf-8 -*-
"""E.V. HTTP 服务：给各种语音端调用。

    POST /ask   {"text": "开下浴霸", "session": "xiaoai"}
             -> {"reply": "浴霸开了", "action": "bath_heater_on",
                 "device": "浴霸", "layer": "L2", "ms": 3,
                 "need_confirm": false, "handled": true}

    GET  /health -> {"ok": true, "capabilities": 65, "model": "mlx" 或 "cloud"}

handled=false 表示 E.V. 管不了这句话（不是家居指令），
语音端应该把它交回原来的助手处理。

用法：
    python3 ev_server.py                # dry-run，不会真动设备
    python3 ev_server.py --real         # 真实控制
    python3 ev_server.py --port 8848
"""
import json, sys, time, pathlib, warnings, threading
warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path(__file__).parent / "ev"))
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent import EV
from capabilities import CAPS

DRY = "--real" not in sys.argv
PORT = int(sys.argv[sys.argv.index("--port")+1]) if "--port" in sys.argv else 8848

_sessions = {}      # session -> EV（每个语音端一份上下文，纠正/确认互不干扰）
_lock = threading.Lock()

def get_ev(session, room=None):
    """每个语音端一个 EV 实例。room = 这个端在哪个房间，
    决定「打开空调」这类没点名房间的指令落在哪台设备上。"""
    with _lock:
        ev = _sessions.get(session)
        if ev is None:
            ev = EV(dry_run=DRY); _sessions[session] = ev
        if room and ev.u.room != room:
            ev.u.room = room
        return ev

# ---- daily loop 手动触发 ----
import subprocess, re as _re
_daily = {"proc": None, "log": pathlib.Path("/tmp/ev_daily_web.log"), "started": None}

def _daily_start():
    p = _daily["proc"]
    if p and p.poll() is None:
        return {"ok": False, "running": True, "msg": "已经在跑了"}
    _daily["log"].write_text("", "utf-8")
    _daily["proc"] = subprocess.Popen(
        [sys.executable, "daily.py"],
        cwd=str(pathlib.Path(__file__).parent / "ev"),
        stdout=_daily["log"].open("w"), stderr=subprocess.STDOUT)
    _daily["started"] = time.time()
    return {"ok": True, "running": True, "pid": _daily["proc"].pid}

def _daily_status():
    p = _daily["proc"]
    running = bool(p and p.poll() is None)
    txt = _daily["log"].read_text("utf-8", errors="ignore") if _daily["log"].exists() else ""
    # 抽出阶段和指标行
    lines = [l.rstrip() for l in txt.splitlines() if l.strip()]
    return {"running": running, "started": _daily["started"],
            "elapsed": round(time.time() - _daily["started"]) if _daily["started"] else 0,
            "exit": (p.poll() if p else None), "lines": lines[-40:]}

class H(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path in ("/", "/console", "/index.html"):
            f = pathlib.Path(__file__).parent / "console.html"
            b = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers(); self.wfile.write(b); return
        if self.path.startswith("/pending"):
            import importlib, pending
            importlib.reload(pending)
            return self._send(pending.survey())
        if self.path.startswith("/daily/status"):
            return self._send(_daily_status())
        if self.path.startswith("/health"):
            ev = get_ev("_probe")
            import understand as _U
            return self._send({"ok": True, "capabilities": len(CAPS),
                               "l2": ("mlx:" + _U.MLX_URL) if _U.MLX_URL else "未配置（全走云端）",
                               "rooms": {k: v.u.room for k, v in _sessions.items() if v.u.room},
                               "dry_run": DRY,
                               "sessions": list(_sessions)})
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        if self.path.startswith("/daily"):
            return self._send(_daily_start())
        if self.path.startswith("/reset"):
            try:
                n = int(self.headers.get("Content-Length", 0))
                sess = (json.loads(self.rfile.read(n) or b"{}")).get("session", "default")
            except Exception:
                sess = "default"
            with _lock: _sessions.pop(sess, None)
            return self._send({"ok": True, "reset": sess})
        if not self.path.startswith("/ask"):
            return self._send({"error": "not found"}, 404)
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self._send({"error": f"bad json: {e}"}, 400)
        text = (body.get("text") or "").strip()
        if not text:
            return self._send({"error": "text is required"}, 400)
        try:
            r = get_ev(body.get("session","default"), body.get("room")).handle(text)
        except Exception as e:
            return self._send({"error": str(e), "handled": False}, 500)
        self._send({
            "reply": r.get("reply"), "action": r.get("action"),
            "actions": r.get("actions"), "device": r.get("device"),
            "layer": r.get("layer"), "ms": r.get("total_ms"),
            "need_confirm": bool(r.get("need_confirm")),
            "handled": bool(r.get("action")),   # false = 不是家居指令，交回原助手
            "room": get_ev(body.get("session","default")).u.room,
        })

    def log_message(self, *a): pass    # 静音默认访问日志

if __name__ == "__main__":
    print(f"E.V. HTTP 服务 :{PORT}" + ("（dry-run，不会真动设备）" if DRY else "（真实控制）"))
    print(f"  能力 {len(CAPS)} 个 | POST /ask  GET /health")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
