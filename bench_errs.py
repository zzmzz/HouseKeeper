import json,sys,time
SYS = "把用户的话映射到家庭助手的动作 id。只输出 JSON：{\"actions\":[\"<id>\"]}"
from mlx_lm import load, generate
from mlx_lm.sample_utils import make_sampler
m,tok=load(sys.argv[1], adapter_path=sys.argv[2])
rows=[json.loads(l) for l in open("finetune/test.jsonl",encoding="utf-8")]
s=make_sampler(temp=0.0); errs=[]
for r in rows:
    u=[x for x in r["messages"] if x["role"]=="user"][0]["content"]
    gold=json.loads([x for x in r["messages"] if x["role"]=="assistant"][0]["content"])["actions"][0]
    p=tok.apply_chat_template([{"role":"system","content":SYS},{"role":"user","content":u}],add_generation_prompt=True)
    out=generate(m,tok,prompt=p,max_tokens=32,sampler=s,verbose=False)
    try:
        d=json.loads(out[out.find("{"):out.rfind("}")+1]); act=(d.get("actions") or [None])[0]
    except Exception: act=None
    if act!=gold: errs.append((u,gold,act))
print(f"错 {len(errs)}/{len(rows)} 条：")
for u,g,a in errs: print(f"  「{u}」\n     应={g}  判={a}")
