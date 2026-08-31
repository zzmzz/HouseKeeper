# -*- coding: utf-8 -*-
"""离线蒸馏：半夜在 Mac mini 上跑，不在用户等待路径上。
流程：收集真实对话 -> 大模型补标注 -> 训新 student -> 回归测试当门槛 -> 过了才换上去
"""
import json, pathlib, shutil, datetime, warnings
warnings.filterwarnings("ignore")
from understand import Understander, Student, call_llm, STORE
import regression

BASE = pathlib.Path(__file__).parent.parent
TRACES = BASE / "traces.jsonl"
MODELS = BASE / "models"; MODELS.mkdir(exist_ok=True)

def collect_new():
    """从真实对话里捞出还没进 store 的说法，交给大模型标注"""
    if not TRACES.exists(): return []
    store = json.loads(STORE.read_text("utf-8"))
    known = set(store["l1"]) | {e["text"] for e in store["examples"]}
    seen=set(); cand=[]
    for line in TRACES.read_text("utf-8").splitlines():
        try: r=json.loads(line)
        except Exception: continue
        t=r.get("text")
        if not t or t in known or t in seen: continue
        seen.add(t)
        # 只捞本地没把握的（L3 兜底过的、或低置信度的）——这些才是学习价值最高的
        if r.get("layer")=="L3" or (r.get("conf") or 1) < 0.6:
            cand.append(t)
    out=[]
    for t in cand:
        a,_=call_llm(t)
        if a: out.append({"text":t,"action":a,"src":"distill"})
    return out

def distill(verbose=True):
    u_old = Understander()
    before = regression.run(u_old, verbose=False, split="gate")      # 晋升门槛只看考卷
    before_tr = regression.run(u_old, verbose=False, split="train")
    if verbose:
        print(f"蒸馏前：考卷 {before['acc']:.1f}% ({before['ok']}/{before['total']})"
              f" | 教材 {before_tr['acc']:.1f}%")

    new = collect_new()
    if verbose: print(f"新捞到 {len(new)} 条真实说法（大模型已标注）")

    store = json.loads(STORE.read_text("utf-8"))
    # 只能拿【教材卷】的失败题当训练材料——考卷绝不能进训练
    hard = [{"text":t,"action":g,"src":"hard"} for t,g,p,c,s in before_tr["fails"]]
    merged = store["examples"] + new + hard
    seen=set(); ex=[]
    for e in merged:
        if e["text"] not in seen: seen.add(e["text"]); ex.append(e)

    # 训新模型
    gate_texts = {i["text"] for i in regression.load("gate")}
    leak = [e["text"] for e in ex if e["text"] in gate_texts]
    if leak:
        print(f"  ⚠️ 拦截 {len(leak)} 条考卷题混入训练，已剔除")
        ex = [e for e in ex if e["text"] not in gate_texts]
    cand_store = {"l1":store["l1"], "examples":ex}
    tmp = BASE/"store.candidate.json"
    tmp.write_text(json.dumps(cand_store,ensure_ascii=False,indent=2),"utf-8")
    import understand as U
    orig=U.STORE; U.STORE=tmp
    u_new = Understander(); U.STORE=orig
    after = regression.run(u_new, verbose=False, split="gate")
    after_tr = regression.run(u_new, verbose=False, split="train")
    if verbose:
        print(f"蒸馏后：考卷 {after['acc']:.1f}% ({after['ok']}/{after['total']})"
              f" | 教材 {after_tr['acc']:.1f}%  样例 {len(store['examples'])} -> {len(ex)}")
        print(f"  （考卷是从未参与训练的题，涨了才算真学会）")

    # 晋升门槛：不许变差
    if after["acc"] >= before["acc"]:
        stamp=datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy(STORE, MODELS/f"store-{stamp}.bak.json")   # 留后路，可回滚
        STORE.write_text(json.dumps(cand_store,ensure_ascii=False,indent=2),"utf-8")
        tmp.unlink(missing_ok=True)
        if verbose: print(f"✅ 晋升（{before['acc']:.1f}% -> {after['acc']:.1f}%），旧版本已备份 store-{stamp}.bak.json")
        return {"promoted":True,"before":before["acc"],"after":after["acc"]}
    tmp.unlink(missing_ok=True)
    if verbose: print(f"❌ 回滚：新模型 {after['acc']:.1f}% 不如旧的 {before['acc']:.1f}%，不换")
    return {"promoted":False,"before":before["acc"],"after":after["acc"]}

if __name__=="__main__":
    print("="*66); print("离线蒸馏（线下跑，不影响运行时）"); print("="*66)
    r=distill()
    print("="*66); print(json.dumps(r,ensure_ascii=False))
