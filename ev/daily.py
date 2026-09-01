# -*- coding: utf-8 -*-
"""日常 loop：1 → n。从真实交互记录持续自我改进。
建议挂夜间定时（家里没人说话时跑）。

  Goal    少走大模型、少被纠正、能力边界更宽
  Action  捞出本地没把握的真实说法 -> 大模型标注 -> 进教材
  Observe 回归考卷 / 纠正率 / 本地接住率
  Feedback 考卷分数决定晋升还是回滚
  Adapt   过了门槛才换模型，旧版本留备份可回滚
"""
import json, os, pathlib, shutil, sys, warnings, datetime
warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pipeline import Run
import regression, llm
from understand import Understander, call_llm, STORE
from capabilities import CAPS

BASE = pathlib.Path(__file__).parent.parent
TRACES = BASE/"traces.jsonl"
MODELS = BASE/"models"; MODELS.mkdir(exist_ok=True)

def collect(run, limit=80):
    """只捞【本地没把握】的真实说法——这些学习价值最高"""
    if not TRACES.exists():
        run.note("还没有交互记录"); return [], {}
    store = json.loads(STORE.read_text("utf-8"))
    known = set(store["l1"]) | {e["text"] for e in store["examples"]}
    gate  = {i["text"] for i in regression.load("gate")}
    stat = {"total":0, "l1":0, "l2":0, "l3":0, "corrections":0}
    seen=set(); cand=[]
    for line in TRACES.read_text("utf-8").splitlines():
        try: r=json.loads(line)
        except Exception: continue
        if r.get("event")=="correction": stat["corrections"]+=1
        lay=(r.get("layer") or "")
        if lay.startswith("L1"): stat["l1"]+=1
        elif lay.startswith("L2"): stat["l2"]+=1
        elif lay.startswith("L3"): stat["l3"]+=1
        stat["total"]+=1
        t=r.get("text")
        if not t or t in known or t in seen or t in gate: continue
        if lay.startswith("L3") or (r.get("conf") or 1) < 0.6:
            seen.add(t); cand.append(t)
    run.metric("交互记录", stat["total"], "条")
    if stat["total"]:
        loc = stat["l1"]+stat["l2"]
        run.metric("本地接住率", f"{loc/stat['total']*100:.0f}%", "",
                   f"L1 {stat['l1']} / L2 {stat['l2']} / L3 {stat['l3']}")
        run.metric("被纠正", stat["corrections"], "次", "越少越好")
    run.metric("待学习的新说法", len(cand), "条")
    return cand[:limit], stat

def label(run, cand):
    """大模型标注（运行时同款提示词，保证口径一致）
    返回 (标注成功的, 大模型也搞不定的)。后者不能丢——它们才是能力缺口的线索。"""
    out=[]; unresolved=[]
    for i,t in enumerate(cand,1):
        try:
            a,_ = call_llm(t)
            if a: out.append({"text":t,"action":a,"src":"daily"})
            else:  unresolved.append(t)
        except Exception:
            unresolved.append(t)
        if i%20==0: run.note(f"已标注 {i}/{len(cand)}")
    run.metric("标注成功", len(out), "条")
    run.metric("大模型也搞不定", len(unresolved), "条", "这些是能力缺口的线索")
    return out, unresolved

def audit_poison(run):
    """质检已学标注，抓被固化的错误（Claude）"""
    store=json.loads(STORE.read_text("utf-8"))
    ex=store["examples"][-120:]
    if not ex: return 0
    from capabilities import action_list_for_teacher
    from understand import HOME_CTX
    lines="\n".join(f'{i}. 「{e["text"]}」-> {e["action"]}' for i,e in enumerate(ex))
    try:
        v=llm.parse_json(llm.smart(
            HOME_CTX+"\n给智能家居助手的标注做质检。动作清单：\n"+action_list_for_teacher()+
            "\n\n特别警惕：开/关反了、房间搞错、询问被当成执行。\n\n【待查标注】\n"+lines+
            '\n\n只输出有问题的：[{"i":序号,"correct":"正确id"}]，没问题输出 []', timeout=300))
    except Exception as e:
        run.note(f"质检跳过：{e}"); return 0
    n=0
    for it in v:
        i=it.get("i")
        if isinstance(i,int) and 0<=i<len(ex) and it.get("correct") in CAPS:
            tgt=ex[i]
            for e in store["examples"]:
                if e["text"]==tgt["text"]:
                    run.note(f"✗ 「{e['text']}」{e['action']} -> {it['correct']}")
                    e["action"]=it["correct"]; n+=1
    if n:
        STORE.write_text(json.dumps(store,ensure_ascii=False,indent=2),"utf-8")
        run.metric("修正毒数据", n, "条", "loop 会放大错误，必须定期质检")
    else:
        run.note("未发现错误标注")
    return n

def distill(run, new):
    """蒸馏 + 晋升门槛：考卷不许变差才准换"""
    u_old = Understander()
    before = regression.run(u_old, verbose=False, split="gate")
    before_tr = regression.run(u_old, verbose=False, split="train")
    run.metric("蒸馏前考卷", f"{before['acc']:.0f}%", "", f"教材 {before_tr['acc']:.0f}%")

    store = json.loads(STORE.read_text("utf-8"))
    hard  = [{"text":t,"action":g,"src":"hard"} for t,g,p,c,s in before_tr["fails"]]
    gate  = {i["text"] for i in regression.load("gate")}
    merged = store["examples"] + new + hard
    seen=set(); ex=[]
    for e in merged:
        if e["text"] in gate: continue          # 铁律
        if e["text"] not in seen: seen.add(e["text"]); ex.append(e)

    cand = {"l1":store["l1"], "examples":ex}
    tmp = BASE/"store.candidate.json"; tmp.write_text(json.dumps(cand,ensure_ascii=False,indent=2),"utf-8")
    import understand as U
    orig=U.STORE; U.STORE=tmp
    try: u_new=Understander()
    finally: U.STORE=orig
    after = regression.run(u_new, verbose=False, split="gate")
    run.metric("蒸馏后考卷", f"{after['acc']:.0f}%", "", f"样例 {len(store['examples'])} -> {len(ex)}")

    if after["acc"] >= before["acc"]:
        stamp=datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy(STORE, MODELS/f"store-{stamp}.bak.json")
        STORE.write_text(json.dumps(cand,ensure_ascii=False,indent=2),"utf-8")
        tmp.unlink(missing_ok=True)
        run.note(f"✅ 晋升 {before['acc']:.0f}% -> {after['acc']:.0f}%（旧版已备份，可回滚）")
        return True, before["acc"], after["acc"]
    tmp.unlink(missing_ok=True)
    run.note(f"❌ 回滚：{after['acc']:.0f}% 不如 {before['acc']:.0f}%，不换")
    return False, before["acc"], after["acc"]

def _lock(name):
    """单实例锁：并发跑会互相覆盖 store.json 和题库，结果不可信"""
    lk = BASE / name
    if lk.exists():
        try: pid = int(lk.read_text().strip())
        except Exception: pid = None
        if pid and pathlib.Path(f"/proc/{pid}").exists():
            sys.exit(f"已有任务在跑（pid {pid}）。等它结束，或先 kill 掉。\n"
                     "并发运行会互相覆盖学习数据和题库，结果不可信。")
        lk.unlink()
    lk.write_text(str(os.getpid()))
    import atexit; atexit.register(lambda: lk.exists() and lk.unlink())

def main():
    _lock(".loop.lock")
    run = Run("daily")
    print("="*70); print("E.V. 日常 Loop：从真实交互持续改进"); print("="*70)
    with run.stage("收集", "只捞本地没把握的——学习价值最高") as r:
        cand, stat = collect(r)
    new=[]
    if cand:
        with run.stage("标注", "大模型当老师") as r:
            new, unresolved = label(r, cand)
    with run.stage("能力缺口", "大模型也搞不定的：分类、攒证据、够了才找人") as r:
        import gaps
        found = gaps.classify(r, unresolved) if unresolved else []
        gs = gaps.merge(r, found)
        gs = gaps.check_done(r)          # 人做完了？系统自己发现
        gaps.notify(r, gs)

    with run.stage("质检已学标注", "抓被固化的错误") as r:
        audit_poison(r)
    if "--lora" in sys.argv:
        with run.stage("重训微调小模型", "把新学的说法练进 0.6B 权重（Mac mini）") as r:
            import retrain_lora
            try: retrain_lora.run_all(r)
            except Exception as e: r.note(f"重训失败（不影响其余阶段）：{e}")

    with run.stage("蒸馏 + 晋升门槛", "考卷不许变差才准换") as r:
        promoted, b, a = distill(r, new)
    run.finish(promoted=promoted, before=b, after=a, learned=len(new))

if __name__=="__main__": main()
