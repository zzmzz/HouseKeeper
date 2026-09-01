# -*- coding: utf-8 -*-
"""微调小模型推理服务（跑在 Mac mini 上）

E.V. 的 L2：一句话进，动作 id 出。约 160ms。

为什么是独立服务而不是塞进 E.V.：
  - 模型要常驻内存（0.43GB），E.V. 主进程重启不该把它带下来
  - Mac mini 有 MLX（Apple 芯片加速），E.V. 跑在别的机器上
  - 挂了 E.V. 能自动降级回内置的 n-gram，不至于全瞎

用法：
    python3 mlx_server.py --port 8850
    python3 mlx_server.py --model mlx-community/Qwen3-0.6B-4bit --adapter adapters-0.6b
"""
import json, sys, time, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def arg(name, default=None):
    return sys.argv[sys.argv.index(name)+1] if name in sys.argv else default

MODEL   = arg("--model", "mlx-community/Qwen3-0.6B-4bit")
ADAPTER = arg("--adapter", "adapters-0.6b")
PORT    = int(arg("--port", "8850"))
SYS_PROMPT = "把用户的话映射到家庭助手的动作 id。只输出 JSON：{\"actions\":[\"<id>\"]}"

print(f"加载 {MODEL} + {ADAPTER} …", flush=True)
from mlx_lm import load, generate
from mlx_lm.sample_utils import make_sampler
import mlx.core as mx
_t0 = time.time()
MODEL_OBJ, TOK = load(MODEL, adapter_path=ADAPTER)
SAMPLER = make_sampler(temp=0.0)
_lock = threading.Lock()
print(f"  就绪 {time.time()-_t0:.1f}s，内存 {mx.get_peak_memory()/1e9:.2f}GB", flush=True)

def infer(text):
    msgs = [{"role":"system","content":SYS_PROMPT},{"role":"user","content":text}]
    p = TOK.apply_chat_template(msgs, add_generation_prompt=True)
    with _lock:                      # MLX 不是线程安全的，串行化
        out = generate(MODEL_OBJ, TOK, prompt=p, max_tokens=32, sampler=SAMPLER, verbose=False)
    try:
        d = json.loads(out[out.find("{"):out.rfind("}")+1])
        acts = d.get("actions") or ([d["action"]] if d.get("action") else [])
        return [a for a in acts if isinstance(a, str)], out
    except Exception:
        return [], out

class H(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.startswith("/health"):
            return self._send({"ok":True,"model":MODEL,"adapter":ADAPTER,
                               "mem_gb":round(mx.get_peak_memory()/1e9,2)})
        self._send({"error":"not found"},404)
    def do_POST(self):
        if not self.path.startswith("/predict"):
            return self._send({"error":"not found"},404)
        try:
            n=int(self.headers.get("Content-Length",0))
            text=(json.loads(self.rfile.read(n) or b"{}").get("text") or "").strip()
        except Exception as e:
            return self._send({"error":str(e)},400)
        if not text: return self._send({"error":"text required"},400)
        t0=time.time(); acts,raw=infer(text); ms=(time.time()-t0)*1000
        self._send({"actions":acts,"ms":round(ms),"raw":raw[:120]})
    def log_message(self,*a): pass

if __name__=="__main__":
    print(f"MLX 推理服务 :{PORT}  POST /predict  GET /health", flush=True)
    ThreadingHTTPServer(("0.0.0.0",PORT),H).serve_forever()
