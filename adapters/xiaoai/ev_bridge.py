# -*- coding: utf-8 -*-
"""E.V. 小爱桥接（open-xiaoai Rust client 版）

和 ev-client.sh（读 instruction.log）的区别：
  日志版：小爱云端**已经决定并执行完**才写日志 -> 我们读到时它已在说话 -> 只能事后打断
  本版本：Rust client 直连，事件到达比日志早，能在小爱开口前就压住

跑在 Mac mini 上（有 open_xiaoai_server 扩展）。音箱端跑 open-xiaoai 的 client：
    ./client ws://<mac-mini-ip>:4399

用法：
    PYTHONPATH=~/code/ev-mlx/libs EV_URL=http://192.168.1.202:8848 \
      /usr/bin/python3 ev_bridge.py
"""
import asyncio, json, os, sys, time, urllib.request

import open_xiaoai_server

EV_URL  = os.environ.get("EV_URL", "http://192.168.1.202:8848")
SESSION = os.environ.get("EV_SESSION", "xiaoai")
ROOM    = os.environ.get("EV_ROOM", "")
TIMEOUT = float(os.environ.get("EV_TIMEOUT", "12"))
MIN_BYTES = 7          # 少于这个字节数当噪音（≈2 个中文字）


def ask_ev(text):
    body = json.dumps({"text": text, "session": SESSION, "room": ROOM}).encode()
    req = urllib.request.Request(EV_URL.rstrip("/") + "/ask", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


class Bridge:
    loop = None
    busy = False
    last_dialog = None

    @classmethod
    async def start(cls):
        cls.loop = asyncio.get_event_loop()
        open_xiaoai_server.register_fn("on_event", cls.on_event)
        print(f"E.V. 桥接已启动 -> {EV_URL}" + (f"（位于 {ROOM}）" if ROOM else ""), flush=True)
        print("音箱端执行： ./client ws://<本机IP>:4399", flush=True)
        await open_xiaoai_server.start_server()

    # ---- Rust 侧回调（同步）----
    DEBUG = os.environ.get("EV_DEBUG") == "1"

    @classmethod
    def on_event(cls, event):
        if cls.DEBUG:
            print(f"[raw] {str(event)[:400]}", flush=True)
        try:
            e = json.loads(event) if isinstance(event, str) else event
        except Exception as ex:
            if cls.DEBUG: print(f"[raw] 解析失败 {ex}", flush=True)
            return
        if e.get("event") != "instruction":
            return
        data = e.get("data") or {}
        line = data.get("NewLine") if isinstance(data, dict) else None
        if not line:
            return
        try:
            d = json.loads(line)
        except Exception:
            return
        h, p = d.get("header", {}), d.get("payload", {})
        if h.get("namespace") != "SpeechRecognizer" or h.get("name") != "RecognizeResult":
            return
        if not p.get("is_final"):
            return
        results = p.get("results") or []
        text = (results[0].get("text") or "").strip() if results else ""
        if not text or len(text.encode()) < MIN_BYTES:
            return
        dialog = h.get("dialog_id")
        if dialog and dialog == cls.last_dialog:
            return
        cls.last_dialog = dialog
        if cls.busy:
            return
        asyncio.run_coroutine_threadsafe(cls.handle(text, dialog), cls.loop)

    # ---- 音箱侧动作 ----
    @staticmethod
    async def shell(cmd, timeout_ms=8000):
        try:
            return await open_xiaoai_server.run_shell(cmd, timeout_ms)
        except Exception:
            return None

    @classmethod
    async def stop_native(cls, dialog=None):
        payload = {"action": "stop"}
        if dialog: payload["dialog_id"] = dialog
        await cls.shell("ubus call mediaplayer player_play_operation '%s'"
                        % json.dumps(payload, ensure_ascii=False))

    @classmethod
    async def speak(cls, text):
        p = json.dumps({"text": text, "save": 0}, ensure_ascii=False).replace("'", "'\\''")
        await cls.shell(f"ubus call mibrain text_to_speech '{p}'")

    @classmethod
    async def handle(cls, text, dialog):
        cls.busy = True
        t0 = time.time()
        try:
            await cls.stop_native(dialog)          # 事件比日志早，这次能赶在它开口前
            try:
                r = await asyncio.to_thread(ask_ev, text)
            except Exception as ex:
                print(f"E.V. 调用失败: {ex}", flush=True)
                await cls.speak("后台没反应，等下再试")
                return
            reply = r.get("reply") or "这个我还做不了"
            print(f"「{text}」-> {reply}  [{r.get('layer')} {r.get('ms')}ms "
                  f"总 {(time.time()-t0)*1000:.0f}ms]", flush=True)
            await cls.stop_native(dialog)          # 说话前再压一次
            await cls.speak(reply)
        finally:
            cls.busy = False


if __name__ == "__main__":
    asyncio.run(Bridge.start())
