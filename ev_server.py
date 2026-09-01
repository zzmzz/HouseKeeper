# -*- coding: utf-8 -*-
"""E.V. HTTP 服务：给各种语音端调用。

    POST /ask   {"text": "开下浴霸", "session": "xiaoai"}
             -> {"reply": "浴霸开了", "action": "bath_heater_on",
                 "device": "浴霸", "layer": "L2", "ms": 3,
                 "need_confirm": false, "handled": true}

    GET  /health -> {"ok": true, "capabilities": 55, "thresh": 0.35}

handled=false 表示 E.V. 管不了这句话（不是家居指令），
语音端应该把它交回原来的助手处理。

用法：
    python3 ev_server.py                # dry-run，不会真动设备
    python3 ev_server.py --real         # 真实控制
    python3 ev_server.py --port 8848
"""
import json, sys, pathlib, warnings, threading
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
        if self.path.startswith("/health"):
            ev = get_ev("_probe")
            return self._send({"ok": True, "capabilities": len(CAPS),
                               "rooms": {k: v.u.room for k, v in _sessions.items() if v.u.room},
                               "thresh": ev.u.thresh, "dry_run": DRY,
                               "sessions": list(_sessions)})
        self._send({"error": "not found"}, 404)

    def do_POST(self):
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
