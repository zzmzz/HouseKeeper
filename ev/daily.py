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

def learn_and_retrain(run, new):
    """把新学的说法并进样例库 -> 重训 0.6B -> 考卷不许变差才准换

    以前这里蒸馏的是 n-gram 分类器（已删除，两个学习器要各自维护、
    各自有晋升门槛，复杂度翻倍却只换来一个备胎）。现在学生只有一个：微调 0.6B。
    """
    store = json.loads(STORE.read_text("utf-8"))
    gate  = {i["text"] for i in regression.load("gate")}
    seen  = {e["text"] for e in store["examples"]}
    added = 0
    for e in new:
        if e["text"] in gate or e["text"] in seen:    # 铁律：考卷不进训练
            continue
        store["examples"].append(e); seen.add(e["text"]); added += 1
    if added:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy(STORE, MODELS/f"store-{stamp}.bak.json")
        STORE.write_text(json.dumps(store, ensure_ascii=False, indent=2), "utf-8")
    run.metric("并入样例", added, "条", f"样例总数 {len(store['examples'])}")
    if not added:
        run.note("没有新样例，跳过重训")
        return False, 0, 0

    import retrain_lora
    r = retrain_lora.run_all(run)      # 内含晋升门槛：考卷不许变差
    return r.get("promoted", False), r.get("before", 0), r.get("after", 0)

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
    with run.stage("学习 + 重训小模型", "并入新样例，重训 0.6B，考卷不许变差才准换") as r:
        promoted, b, a = learn_and_retrain(r, new)
    run.finish(promoted=promoted, before=b, after=a, learned=len(new))

if __name__=="__main__": main()
