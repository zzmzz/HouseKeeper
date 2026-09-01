# -*- coding: utf-8 -*-
"""多意图考卷（端到端，含拆解逻辑）"""
import json, sys, pathlib, time, os, warnings
warnings.filterwarnings("ignore")
os.environ.setdefault("EV_MLX_URL","http://192.168.8.188:8850")
sys.path.insert(0, str(pathlib.Path(__file__).parent / "ev"))
from agent import EV
rows = json.loads((pathlib.Path(__file__).parent/"multi_test.json").read_text("utf-8"))
ev = EV(dry_run=True, learn=False)
ok=0; lat=[]; byl={}
for r in rows:
    t0=time.time(); res=ev.handle(r["text"]); lat.append((time.time()-t0)*1000)
    acts=res.get("actions") or []
    good = set(acts)==set(r["actions"]); ok+=good
    byl[res.get("layer")] = byl.get(res.get("layer"),0)+1
    if not good:
        print(f"  ✗ 「{r['text'][:26]}」-> {acts}  应为 {r['actions']}")
n=len(rows); lat.sort()
print(f"\n多意图考卷 {ok}/{n} = {ok/n*100:.0f}%")
print(f"延迟 中位 {lat[n//2]:.0f}ms")
print(f"层分布 {byl}")
