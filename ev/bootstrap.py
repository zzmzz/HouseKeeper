# -*- coding: utf-8 -*-
"""冷启动：0 → 成熟。只给一份 capabilities.md，自动跑到可用状态。

这条流水线把踩过的坑固化成了自动步骤——用它的人不用重蹈：
  · 注册表漏设备 -> 模型拿相似的顶上      => 阶段1 自动体检
  · 易混能力没写辨析 -> 开关/房间判反      => 阶段2 自动生成辨析
  · 样例太少 -> 分类器根本训不起来         => 阶段3 每能力补足
  · 拿考卷当教材 -> 分数虚高               => 阶段4 分卷，gate 永不参与训练
  · 阈值拍脑袋 -> 白白多走大模型           => 阶段6 跑曲线自动选
  · L1 写死过度泛化 -> 永久生效无人察觉     => 阶段7 审计

用法：python3 bootstrap.py [--per 18] [--skip-audit]
"""
import json, os, pathlib, sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pipeline import Run
import llm, regression
from capabilities import CAPS, action_list_for_teacher
from understand import HOME_CTX, STORE, Understander, META

BASE = pathlib.Path(__file__).parent.parent
PER  = 18

def _json(prompt, timeout=300):
    return llm.parse_json(llm.smart(prompt, timeout=timeout))

# ---------- 阶段 1：体检注册表 ----------
def audit_registry(run):
    import audit_registry as AR
    try:
        items, n_live, n_reg = AR.audit()
    except Exception as e:
        run.note(f"体检跳过（{e}）"); return []
    run.metric("家里活跃可控实体", n_live)
    run.metric("已登记", n_reg)
    if items:
        run.note(f"发现 {len(items)} 个可能漏登记的设备：")
        for it in items[:6]:
            run.note(f"  · {it.get('name')} — {str(it.get('why'))[:60]}")
        run.note("（不自动加，需人工确认实体是否正确；见事故记录：漏登记会导致张冠李戴）")
    else:
        run.note("没发现明显遗漏")
    return items

# ---------- 阶段 2：自动生成「辨析」 ----------
def gen_conflicts(run):
    """找出易混能力对，让 Claude 写辨析写回 capabilities.md。
    辨析是防「开/关判反」「房间搞错」的主力，原来靠人踩坑后手写。"""
    md = BASE/"ev"/"capabilities.md"
    text = md.read_text("utf-8")
    missing = [a for a,c in CAPS.items() if not c.get("conflict")]
    if not missing:
        run.note("所有能力都已有辨析"); return 0
    run.note(f"{len(missing)} 个能力缺辨析，交给 Claude 补")
    prompt = f"""{HOME_CTX}
下面是一个家庭语音助手的能力清单。有些能力**极易被模型混淆**，典型三类：
1. 开/关反了（light_living_on vs light_living_off）
2. 房间搞错（客厅空调 vs 主卧空调）——**操作错房间比不操作更糟**
3. 询问 vs 执行（问湿度多少 ≠ 开加湿器）

【完整清单】
{action_list_for_teacher()}

给下面这些还没有「辨析」的能力，各写一句辨析，明确指出它最容易和谁混、怎么区分。
需要写的：{', '.join(missing)}

只输出 JSON：{{"能力id": "辨析文字", ...}}。辨析要短、要具体、要点名易混的那个 id。"""
    try:
        got = _json(prompt)
    except Exception as e:
        run.note(f"生成失败：{e}"); return 0
    n = 0
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]; out.append(ln); i += 1
        if not ln.startswith("### "): continue
        aid = ln[4:].split("·")[0].strip()
        # 原样搬运该能力已有的 何时/辨析 行
        block = []
        while i < len(lines) and (lines[i].startswith("何时：") or lines[i].startswith("辨析：")):
            block.append(lines[i]); i += 1
        out.extend(block)
        if aid in got and aid in missing and not any(b.startswith("辨析：") for b in block):
            out.append(f"辨析：{got[aid]}"); n += 1
    md.write_text("\n".join(out) + "\n", "utf-8")
    run.metric("补写辨析", n, "条")
    return n

# ---------- 阶段 3：造训练数据 ----------
def gen_training(run, per=PER):
    import importlib, capabilities as C
    importlib.reload(C)
    gate = {i["text"] for i in regression.load("gate")}
    store = json.loads(STORE.read_text("utf-8")) if STORE.exists() else {"l1":{}, "examples":[]}
    store.setdefault("l1", {}); store.setdefault("examples", [])
    # 出厂种子：能力名进 L1
    for aid, c in C.CAPS.items(): store["l1"].setdefault(c["name"], aid)
    have = {e["text"] for e in store["examples"]}
    added = dropped = 0
    caps = list(C.CAPS.items())
    for i,(aid,c) in enumerate(caps,1):
        cur = sum(1 for e in store["examples"] if e["action"]==aid)
        if cur >= per: continue
        prompt = f"""{HOME_CTX}
为家庭语音助手造训练数据。

【全部可用动作】
{C.action_list_for_teacher()}

只为这一个动作生成用户说法：
  id：{aid}　含义：{c['name']}
  什么时候用：{c.get('use','')}
  辨析：{c.get('conflict','')}

写 {per-cur} 条这家人日常真会说的话：口语化、长短不一，覆盖直接命令/带理由/带情绪/省略主语/礼貌语气。
**绝不能**写成清单里其它动作的说法，特别注意：开vs关、热vs冷、询问vs执行、哪个房间、单动作vs整套场景。
只输出 JSON 字符串数组。"""
        try: texts = _json(prompt)
        except Exception as e:
            run.note(f"[{i}/{len(caps)}] {aid} 失败：{e}"); continue
        n=0
        for t in texts:
            if not isinstance(t,str) or not t.strip(): continue
            t=t.strip()
            if t in gate: dropped+=1; continue        # 铁律：不碰考卷
            if t in have: continue
            store["examples"].append({"text":t,"action":aid,"src":"bootstrap"})
            have.add(t); n+=1; added+=1
        if i%10==0 or i==len(caps): run.note(f"[{i}/{len(caps)}] 累计 {added} 条")
        STORE.write_text(json.dumps(store,ensure_ascii=False,indent=2),"utf-8")
    # 教本地认「用户在纠正我」
    if not any(e["action"]==META for e in store["examples"]):
        try:
            ph=_json(HOME_CTX+"\n生成用户『纠正智能助手刚才做错的事』时会说的话，30条，口语化多样："
                     "直接否定/指正对象/让撤销/抱怨式。只输出 JSON 字符串数组。")
            for t in ph:
                if isinstance(t,str) and t.strip() and t.strip() not in have:
                    store["examples"].append({"text":t.strip(),"action":META,"src":"bootstrap"}); added+=1
            STORE.write_text(json.dumps(store,ensure_ascii=False,indent=2),"utf-8")
            run.note("已教会本地识别『用户在纠正我』")
        except Exception: pass
    run.metric("训练样例", len(store["examples"]), "条")
    run.metric("因撞考卷丢弃", dropped, "条", "训练/测试分离的铁律")
    return added

# ---------- 阶段 4：造回归考卷 ----------
def gen_regression(run, per=6):
    items = regression.grow(per=per, only_missing=True)
    from collections import Counter
    c = Counter(i["split"] for i in items)
    run.metric("题库", len(items), "题")
    run.metric("教材卷 / 考卷", f"{c.get('train',0)} / {c.get('gate',0)}", "",
               "考卷永不参与训练，这是防自我欺骗的关键")
    return items

# ---------- 阶段 5：训练 ----------
def train(run):
    u = Understander()
    u.retrain(use_cache=False)
    run.metric("类别数", len(u.student.labels or []))
    return u

# ---------- 阶段 6：自动选阈值 ----------
def tune_threshold(run, u):
    items = regression.load("gate")
    if not items:
        run.note("考卷为空 —— 造题阶段可能全失败了，请检查上面的报错。用保守默认 0.40")
        return 0.40, []
    preds=[]
    for it in items:
        if it["text"] in u.store["l1"]: p,c = u.store["l1"][it["text"]], 1.0
        else: p,c = u.student.predict(it["text"])
        preds.append((p==it["action"], c))
    curve=[]
    for th in [0.15,0.20,0.25,0.30,0.35,0.40,0.45,0.50,0.55]:
        hi=[ok for ok,c in preds if c>=th]
        n=len(hi); acc=(sum(hi)/n*100) if n else 100.0
        curve.append({"th":th,"hit":round(n/len(preds)*100,1),"acc":round(acc,1)})
    # 甜点：本地接住越多越快，但答错要付纠正代价。
    # 记分 = 接住率 - 错误率×K。K=6 表示"答错 1 次的代价 ≈ 少接住 6 次"
    # （答错要用户纠正、可能已经动了设备；少接住只是慢 1 秒）
    K = 6
    for c in curve: c["score"] = round(c["hit"] - (100-c["acc"])*K, 1)
    best = max(curve, key=lambda x: x["score"])
    run._emit("curve", name="threshold", points=curve)
    for c in curve:
        run.note(f"阈值 {c['th']:.2f}  本地接住 {c['hit']:>5.1f}%  答对 {c['acc']:>5.1f}%  记分 {c['score']:>6.1f}"
                 + ("   ← 选它" if c["th"]==best["th"] else ""))
    run.metric("选定阈值", best["th"], "", f"接住 {best['hit']}%，答对 {best['acc']}%")
    return best["th"], curve

# ---------- 阶段 7：审计 L1 ----------
def audit_l1(run):
    import audit_l1 as A1
    try:
        issues, l1 = A1.audit()
    except Exception as e:
        run.note(f"审计跳过（{e}）"); return 0
    if not issues:
        run.note(f"L1 {len(l1)} 条，未发现问题"); return 0
    for it in issues:
        run.note(f"✗ 「{it.get('text')}」-> {it.get('current')} [{it.get('verdict')}] {str(it.get('why'))[:50]}")
    r,f = A1.apply(issues)
    run.metric("清理过度泛化规则", r+f, "条", "L1 优先级最高且不会弃权，错了永久生效")
    return r+f

# ---------- 阶段 8：验收 ----------
def evaluate(run, thresh):
    u = Understander(thresh)
    g = regression.run(u, verbose=False, split="gate")
    t = regression.run(u, verbose=False, split="train")
    run.metric("考卷（从未训练）", f"{g['acc']:.0f}%", "", f"{g['ok']}/{g['total']}")
    run.metric("教材（训练过）", f"{t['acc']:.0f}%")
    gap = t["acc"]-g["acc"]
    run.metric("过拟合差距", f"{gap:.0f}", "pt", "差距大 = 只是背下来了")
    items = regression.load("gate")
    hi=[]; lo=0
    for it in items:
        if it["text"] in u.store["l1"]: p,c = u.store["l1"][it["text"]],1.0
        else: p,c = u.student.predict(it["text"])
        if c>=thresh: hi.append(p==it["action"])
        else: lo+=1
    if hi:
        run.metric("本地接住", f"{len(hi)/len(items)*100:.0f}%", "",
                   f"其中答对 {sum(hi)/len(hi)*100:.0f}%")
    run.metric("弃权降级", f"{lo/len(items)*100:.0f}%", "", "宁可多走大模型，不自信做错事")
    return {"gate":g["acc"], "train":t["acc"], "gap":gap,
            "local_hit":round(len(hi)/len(items)*100,1) if items else 0,
            "local_acc":round(sum(hi)/len(hi)*100,1) if hi else 0}

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
    _lock(".bootstrap.lock")
    per = PER
    if "--per" in sys.argv: per = int(sys.argv[sys.argv.index("--per")+1])
    run = Run("bootstrap")
    print("="*70); print("E.V. 冷启动：0 → 成熟"); print("="*70)
    print(f"输入：capabilities.md（{len(CAPS)} 个能力）")
    print("输出：可用的三层助手 + 考卷成绩 + 选定阈值\n")

    if "--skip-audit" not in sys.argv:
        with run.stage("体检能力注册表", "查漏设备，防『拿相似的顶上』") as r:
            audit_registry(r)
    with run.stage("自动生成辨析", "防开关判反 / 房间搞错") as r:
        gen_conflicts(r)
    with run.stage("造回归考卷", "先造考卷，后造教材——顺序不能反") as r:
        gen_regression(r)
    with run.stage("造训练数据", f"每能力 {per} 条，撞考卷的一律丢弃") as r:
        gen_training(r, per)
    with run.stage("训练本地小模型") as r:
        u = train(r)
    with run.stage("自动选阈值", "跑取舍曲线，不拍脑袋") as r:
        thresh, curve = tune_threshold(r, u)
    with run.stage("审计 L1 规则表", "最危险的一层：最高优先级且不会弃权") as r:
        audit_l1(r)
    with run.stage("验收") as r:
        res = evaluate(r, thresh)

    (BASE/"tuned.json").write_text(json.dumps({"thresh":thresh},ensure_ascii=False),"utf-8")
    run.finish(**res, thresh=thresh)
    print("\n下一步：python3 agent.py  开始用；python3 daily.py  日常自我改进")

if __name__=="__main__": main()
