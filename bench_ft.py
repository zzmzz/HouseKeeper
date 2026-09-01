# -*- coding: utf-8 -*-
"""对比：极简提示词下，各模型在考卷上的准确率和延迟。
微调后能力清单进了权重，提示词只有 48 字符 —— 这才是本地小模型的正确用法。
"""
import json, sys, time
MODEL = sys.argv[sys.argv.index("--model")+1] if "--model" in sys.argv else "mlx-community/Qwen3-1.7B-4bit"
ADAPTER = sys.argv[sys.argv.index("--adapter")+1] if "--adapter" in sys.argv else None
N = int(sys.argv[sys.argv.index("--n")+1]) if "--n" in sys.argv else 60
SYS = "把用户的话映射到家庭助手的动作 id。只输出 JSON：{\"actions\":[\"<id>\"]}"

def main():
    from mlx_lm import load, generate
    from mlx_lm.sample_utils import make_sampler
    import mlx.core as mx
    t0=time.time()
    model, tok = load(MODEL, adapter_path=ADAPTER) if ADAPTER else load(MODEL)
    print(f"{MODEL}{' + '+ADAPTER if ADAPTER else ''}")
    print(f"  加载 {time.time()-t0:.1f}s  内存 {mx.get_peak_memory()/1e9:.2f}GB", flush=True)
    rows=[json.loads(l) for l in open("finetune/test.jsonl",encoding="utf-8")][:N]
    sampler=make_sampler(temp=0.0); ok=0; lat=[]
    for r in rows:
        u=[m for m in r["messages"] if m["role"]=="user"][0]["content"]
        gold=json.loads([m for m in r["messages"] if m["role"]=="assistant"][0]["content"])["actions"][0]
        p=tok.apply_chat_template([{"role":"system","content":SYS},{"role":"user","content":u}],
                                  add_generation_prompt=True)
        t=time.time(); out=generate(model,tok,prompt=p,max_tokens=32,sampler=sampler,verbose=False)
        lat.append((time.time()-t)*1000)
        try:
            d=json.loads(out[out.find("{"):out.rfind("}")+1]); act=(d.get("actions") or [None])[0]
        except Exception: act=None
        ok += (act==gold)
    n=len(rows); lat.sort()
    print(f"  准确率 {ok}/{n} = {ok/n*100:.0f}%")
    print(f"  延迟 中位 {lat[n//2]:.0f}ms  P90 {lat[int(n*0.9)]:.0f}ms")
    print(f"  峰值内存 {mx.get_peak_memory()/1e9:.2f}GB", flush=True)

if __name__=="__main__": main()
