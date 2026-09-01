# -*- coding: utf-8 -*-
"""小爱音箱 Pro 适配器（open-xiaoai 协议，纯 Python 实现）

**不需要 Rust / maturin / 编译。** 音箱端的 client 说的是普通 WebSocket
（tokio-tungstenite），消息是 JSON，所以直接用 Python 当服务端即可。

思路：不碰音频。小爱原生的 ASR 和 TTS 都好用，我们只接管中间的「理解 + 执行」。

    小爱麦克风 ─► 原生 ASR ─► 文本事件 ─► [本适配器] ─► E.V. HTTP ─► 执行
    小爱扬声器 ◄─ 原生 TTS ◄── 回答文本 ◄────────────────────────────┘
                                    │
                                    └─ 不归 E.V. 管 ─► 交回原来的小爱

协议（见 open-xiaoai/packages/client-rust/src/services/connect/data.rs）：
    收 {"Event":    {"id","event","data"}}      事件（语音识别结果、播放状态…）
    收 {"Response": {"id","code","msg","data"}} 我们发的 Request 的回执
    发 {"Request":  {"id","command","payload"}} 让音箱执行（run_shell 等）

用法：
    export EV_URL=http://192.168.8.202:8848    # E.V. 服务
    python3 ev_xiaoai.py                       # 默认监听 :4399
音箱端：  ./client ws://<本机IP>:4399
"""
import asyncio, json, os, uuid

try:
    import websockets
except ImportError:
    raise SystemExit("需要 websockets：pip3 install websockets")

import urllib.request

EV_URL  = os.environ.get("EV_URL", "http://127.0.0.1:8848")
SESSION = os.environ.get("EV_SESSION", "xiaoai")
PORT    = int(os.environ.get("EV_WS_PORT", "4399"))
TIMEOUT = float(os.environ.get("EV_TIMEOUT", "15"))
# 设了就只处理以它开头的话；留空 = 接管全部语音
PREFIX  = os.environ.get("EV_PREFIX", "").strip()
DEBUG   = os.environ.get("EV_DEBUG", "") == "1"


def ask_ev(text: str) -> dict:
    body = json.dumps({"text": text, "session": SESSION}).encode()
    req = urllib.request.Request(EV_URL.rstrip("/") + "/ask", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


class Speaker:
    """一个音箱连接"""

    def __init__(self, ws):
        self.ws = ws
        self.busy = False          # 正在处理，忽略期间的识别结果

    async def request(self, command: str, payload=None):
        msg = {"Request": {"id": str(uuid.uuid4()), "command": command,
                           "payload": payload}}
        await self.ws.send(json.dumps(msg, ensure_ascii=False))

    async def shell(self, cmd: str, timeout_ms: int = 10000):
        await self.request("run_shell", {"script": cmd, "timeout": timeout_ms})

    @staticmethod
    def _q(s: str) -> str:
        return s.replace("'", "'\\''")

    async def speak(self, text: str):
        """小爱原生 TTS"""
        p = json.dumps({"text": text, "save": 0}, ensure_ascii=False)
        await self.shell(f"ubus call mibrain text_to_speech '{self._q(p)}'")

    async def hand_back(self, text: str):
        """交回原来的小爱（天气/百科/放歌它本来就会）"""
        p = json.dumps({"nlp": 1, "nlp_text": text}, ensure_ascii=False)
        await self.shell(f"ubus call mibrain ai_service '{self._q(p)}'")

    async def stop_native(self):
        """打断小爱自己的回答，避免和我们的回答重叠"""
        await self.shell("ubus call pnshelper event_notify '{\"src\":3,\"event\":7}'")

    # ---- 事件处理 ----
    async def on_message(self, raw: str):
        try:
            m = json.loads(raw)
        except Exception:
            return
        if "Event" in m:
            await self.on_event(m["Event"])
        elif DEBUG and "Response" in m:
            print("  <resp>", str(m["Response"])[:120])

    async def on_event(self, e: dict):
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
            return                                  # 只处理最终识别结果
        results = p.get("results") or []
        text = (results[0].get("text") or "").strip() if results else ""
        if text and not self.busy:
            await self.handle(text)

    async def handle(self, text: str):
        self.busy = True
        try:
            spoken = text
            if PREFIX:
                if not text.startswith(PREFIX):
                    return                          # 没带前缀，不插手
                spoken = text[len(PREFIX):].strip() or text

            await self.stop_native()

            try:
                r = await asyncio.to_thread(ask_ev, spoken)
            except Exception as ex:
                print("E.V. 调用失败:", ex)
                await self.hand_back(text)          # E.V. 挂了退回原生，别让音箱哑掉
                return

            print(f"「{spoken}」-> {r.get('reply')}  "
                  f"[{r.get('layer')} {r.get('ms')}ms handled={r.get('handled')}]")

            if r.get("handled") or r.get("need_confirm"):
                await self.speak(r.get("reply") or "好了")
            else:
                await self.hand_back(text)          # 不是家居指令，交回小爱
        finally:
            self.busy = False


async def serve(ws):
    peer = getattr(ws, "remote_address", ("?",))[0]
    print(f"✅ 音箱已连接: {peer}")
    sp = Speaker(ws)
    try:
        async for raw in ws:
            if isinstance(raw, bytes):
                continue                            # 音频流，我们不处理
            await sp.on_message(raw)
    except Exception as e:
        print("连接异常:", e)
    finally:
        print(f"❌ 音箱断开: {peer}")


async def main():
    print(f"E.V. 小爱适配器  ws://0.0.0.0:{PORT}  -> {EV_URL}")
    print(f"  {'需前缀「'+PREFIX+'」' if PREFIX else '接管全部语音'}")
    print(f"  音箱端执行： ./client ws://<本机IP>:{PORT}")
    async with websockets.serve(serve, "0.0.0.0", PORT, max_size=None):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
