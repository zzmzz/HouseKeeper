# -*- coding: utf-8 -*-
"""多意图考卷（从未参与训练）。判对的标准：动作集合一致，顺序不计。"""
import json, sys, pathlib, time
sys.path.insert(0, str(pathlib.Path(__file__).parent / "ev"))
from understand import mlx_predict

rows = json.loads((pathlib.Path(__file__).parent/"multi_test.json").read_text("utf-8"))
ok = 0; lat = []
print(f"{'输入':<30}{'预测':<44}对?")
print("-"*90)
for r in rows:
    t0=time.time(); acts,_ = mlx_predict(r["text"]); lat.append((time.time()-t0)*1000)
    good = set(acts) == set(r["actions"]); ok += good
    print(f"{r['text'][:28]:<30}{str(acts)[:42]:<44}{'✓' if good else '✗ '+str(r['actions'])}")
n=len(rows); lat.sort()
print("-"*90)
print(f"多意图考卷 {ok}/{n} = {ok/n*100:.0f}%  |  延迟中位 {lat[n//2]:.0f}ms")
