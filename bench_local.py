# -*- coding: utf-8 -*-
"""本地 4B 模型能不能替代云端 L3？用我们自己的真实提示词和考卷测。

关键不是跑分，是三件事：
  1. 准确率能不能接近云端（DeepSeek）
  2. 延迟能不能接受（含 prompt cache 的效果）
  3. 内存开销 Mac mini 扛不扛得住
"""
import json, sys, time, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent / "ev"))
import regression
from understand import runtime_prompt

N = int(sys.argv[sys.argv.index("--n")+1]) if "--n" in sys.argv else 40
MODEL = sys.argv[sys.argv.index("--model")+1] if "--model" in sys.argv else \
        "mlx-community/Qwen3-4B-Instruct-2507-4bit"

def main():
    from mlx_lm import load, generate
    from mlx_lm.sample_utils import make_sampler
    import mlx.core as mx

    print(f"加载 {MODEL} …", flush=True)
    t0 = time.time(); model, tok = load(MODEL); load_s = time.time()-t0
    mem = mx.get_peak_memory()/1e9
    print(f"  加载 {load_s:.1f}s，峰值内存 {mem:.2f}GB\n", flush=True)

    sysmsg = runtime_prompt()
    ptoks = len(tok.encode(sysmsg))
    print(f"提示词 {ptoks} token（65 个能力清单）\n", flush=True)

    items = regression.load("gate")[:N]
    sampler = make_sampler(temp=0.0)
    ok = 0; lat = []
    print(f"{'输入':<24}{'预测':<22}{'耗时':<9}对?")
    print("-"*66)
    for it in items:
        msgs = [{"role":"system","content":sysmsg},{"role":"user","content":it["text"]}]
        prompt = tok.apply_chat_template(msgs, add_generation_prompt=True)
        t0 = time.time()
        out = generate(model, tok, prompt=prompt, max_tokens=48, sampler=sampler, verbose=False)
        ms = (time.time()-t0)*1000; lat.append(ms)
        act = None
        try:
            s = out[out.find("{"):out.rfind("}")+1]
            d = json.loads(s)
            a = d.get("actions") or ([d["action"]] if d.get("action") else [])
            act = a[0] if a else None
        except Exception: pass
        good = act == it["action"]; ok += good
        print(f"{it['text'][:22]:<24}{str(act)[:20]:<22}{ms:>6.0f}ms  {'✓' if good else '✗ '+it['action']}")
    n=len(items)
    lat.sort()
    print("-"*66)
    print(f"准确率 {ok}/{n} = {ok/n*100:.0f}%")
    print(f"延迟 中位 {lat[n//2]:.0f}ms  最快 {lat[0]:.0f}ms  最慢 {lat[-1]:.0f}ms")
    print(f"峰值内存 {mx.get_peak_memory()/1e9:.2f}GB")

if __name__ == "__main__": main()
