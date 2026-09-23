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
from understand import Understander, call_llm, STORE, save_json
from capabilities import CAPS
import samples as SP

BASE = pathlib.Path(__file__).parent.parent
TRACES = BASE/"traces.jsonl"
MODELS = BASE/"models"; MODELS.mkdir(exist_ok=True)

def collect_unsupported(run, limit=200):
    """捞出"系统如实说了做不到"的那些话。

    这类在日志里长得和成功一模一样：有 action、ok=true、回答也切题
    （「家里空调只接了开关，调不了温度」确实是对「空调调高点」的正确回答）。
    于是三条收集渠道全都漏掉它：
      · unresolved 只收"没接住"的     —— 它接住了
      · 回答质检只抓"答非所问"        —— 它答得很切题
      · collect 只捞"本地没把握"的    —— 它 L2 就很确定
    结果是**用户反复问、系统反复如实拒绝，而缺口队列里永远不出现这一条**。
    ——「空调调高点」问了多次都没进队列，就是这么漏的。

    识别靠能力上的 declares_unsupported 标记，不靠 id 里有没有 "unsupported"
    这种字面约定（那种约定迟早有人不遵守）。
    """
    if not TRACES.exists(): return []
    from capabilities import CAPS as _C
    flagged = {a for a, c in _C.items() if c.get("declares_unsupported")}
    seen, out = set(), []
    for line in TRACES.read_text("utf-8").splitlines()[-limit*4:]:
        try: r = json.loads(line)
        except Exception: continue
        # 两种"如实拒绝"：
        #   ① 命中了专门声明做不到的能力（如 ac_temp_unsupported）
        #   ② L3 自己判断做不到并标了 unsupported（能力清单里压根没这条，
        #      action=null——「执行起床场景」就是这种，四条渠道以前全漏）
        hit = (r.get("action") in flagged) or bool(r.get("unsupported"))
        if hit and r.get("text") and r.get("text") not in seen:
            seen.add(r["text"]); out.append(r["text"])
    if out:
        run.metric("如实拒绝", len(out), "条", "系统答得没错，但这是缺口——" + "、".join(out[:3]))
    return out[-limit:]


# 只学语音来源的。**这条是必须的**：我 curl 测试打过几百条、演示页上也敲过，
# 它们和用户真说的话混在一个日志里。不过滤的话训练集会被测试输入稀释，
# 而"按用户真实说法训练"这件事根本无法执行。
# origin 缺失的按语音算——那是加来源标记之前的老记录，宁可多学不要漏。
LEARN_ORIGINS = {"voice", None, "unknown"}


def collect(run, limit=80):
    """只捞【本地没把握】的真实说法——这些学习价值最高"""
    if not TRACES.exists():
        run.note("还没有交互记录"); return [], {}
    store = json.loads(STORE.read_text("utf-8"))
    known = set(store["l1"]) | {e["text"] for e in store["examples"]}
    gate  = {i["text"] for i in regression.load("gate")}
    stat = {"total":0, "l1":0, "l2":0, "l3":0, "corrections":0}
    seen=set(); cand=[]
    skipped_test = 0
    for line in TRACES.read_text("utf-8").splitlines():
        try: r=json.loads(line)
        except Exception: continue
        if r.get("origin") not in LEARN_ORIGINS:
            skipped_test += 1; continue      # 测试输入不进训练
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
    run.metric("待学习的新说法", len(cand), "条",
               ("已排除 %d 条测试输入（演示页/curl，不该进训练）" % skipped_test)
               if skipped_test else "")
    return cand[:limit], stat

def collect_multi(run):
    """多意图回流：把 L3（老师）在真实交互里拆对的多意图收进 store["multi"]。

    为什么需要它：gen_multi2 造的是拼接样本——标签完美、数量无上限，但句子
    是合成口语。真实说法的分布只有真实交互里有。两个数据源互补，所以回流的
    带 src 标记，gen_multi2 重跑时不会覆盖掉（见 gen_multi2.build_all）。

    为什么只收 L3 的：L2 自己拆出来的结果再喂给 L2 就是自举，会把它自己的
    偏好放大成"事实"。老师的输出才算新信息——和单意图那条线同一个分工。
    """
    if not TRACES.exists():
        return 0
    store = json.loads(STORE.read_text("utf-8"))
    store.setdefault("multi", [])
    have = {m["text"] for m in store["multi"]}
    gate = {i["text"] for i in regression.load("gate")}
    mt = BASE/"multi_test.json"
    gate_multi = {t["text"] for t in json.loads(mt.read_text("utf-8"))} if mt.exists() else set()

    cand, prev_idx, skipped_l2 = [], None, 0
    for line in TRACES.read_text("utf-8").splitlines():
        try: r = json.loads(line)
        except Exception: continue
        if r.get("event") == "correction":
            if prev_idx is not None: cand[prev_idx] = None   # 上一条紧接着被纠正，作废
            prev_idx = None
            continue
        prev_idx = None
        acts = r.get("actions") or []
        if len(acts) < 2 or not r.get("ok"): continue
        if r.get("origin") not in LEARN_ORIGINS: continue    # 和 collect 同一个口径
        lay = r.get("layer") or ""
        if not lay.startswith("L3"):
            skipped_l2 += 1; continue                        # L2 自己拆的不回流
        t = r.get("text")
        if not t or t in have or t in gate or t in gate_multi: continue
        if any(a not in CAPS for a in acts): continue        # 能力已删/改名的旧记录
        have.add(t); cand.append({"text": t, "actions": acts, "src": "daily_multi"})
        prev_idx = len(cand) - 1

    rows = [c for c in cand if c]
    if rows:
        store["multi"] += rows
        save_json(STORE, store)
    run.metric("多意图回流", len(rows), "条",
               ("教材里现有 %d 条；跳过 L2 自己拆的 %d 条" % (len(store["multi"]), skipped_l2))
               if rows else ("只收老师拆对的，跳过 L2 自己拆的 %d 条" % skipped_l2))
    return len(rows)

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

def audit_answers(run, limit=60, rows=None, on_progress=None):
    """回答质量后置质检：抓「匹配到了动作、但根本没回答问题」的情况。

    这类最阴——它不报错、不走 out_of_scope，日志里 ok=true，看指标一切正常。
    实例：问「家里甲醛超标了吗」命中了 air_quality，回答却只有温湿度，
    一个甲醛字都没有。用户听着像被敷衍，系统却以为自己答对了。
    单看意图分类永远发现不了，必须拿「问题+实际回答」一起让大模型复核。

    查出来的并不当场改分类——多数根本不是分类错了，而是**能力本身有缺口**
    （家里就没有甲醛传感器）。所以它们和 out_of_scope 走同一个出口：
    进 gaps 分类，该自动补的自动补，该买硬件的记 TODO。
    """
    if rows is None:
        if not TRACES.exists(): return []
        rows=_recent_traces(limit)
    if not rows: return []
    return _audit_rows(run, rows, on_progress)


def _recent_traces(limit):
    rows=[]
    for line in TRACES.read_text("utf-8").splitlines()[-limit*3:]:
        try: r=json.loads(line)
        except Exception: continue
        if r.get("event")=="undo" or r.get("out_of_scope"): continue
        if not r.get("action") or not r.get("reply"): continue
        rows.append(r)
    return rows[-limit:]


def _polarity_scan(rows):
    """零成本的极性扫描，跑在大模型质检之前。

    大模型的回答质检盯的是"答非所问"（问甲醛答温湿度），
    对"说开却关了"这种**方向反了**反而不敏感——它看到「开所有灯」配
    「所有灯都关掉了」，容易读成"执行了一个关灯动作，语义连贯"。
    实测那三条全反，它一条没报。
    极性是能确定判定的，不该交给模型去猜。
    """
    import agent as _A
    bad = []
    for r in rows:
        t, a, rp = r.get("text") or "", r.get("action") or "", r.get("reply") or ""
        if a and _A.polarity_conflict(t, a):
            bad.append((r, "动作方向相反：%s" % a)); continue
        # L3 直接答复的没有 action，只能看回复本身
        if not a and rp:
            said_on = any(w in t for w in ("打开", "开一下", "开所有", "全开", "点亮")) or (
                t.startswith("开") and "关" not in t)
            said_off = any(w in t for w in ("关掉", "关上", "关了", "全关", "熄")) or (
                t.startswith("关") and "开" not in t)
            rep_on = any(w in rp for w in ("开了", "打开了", "已开", "都开"))
            rep_off = any(w in rp for w in ("关了", "关掉", "已关", "都关"))
            if (said_on and rep_off and not rep_on) or (said_off and rep_on and not rep_off):
                bad.append((r, "回复方向和指令相反"))
    return bad


def _audit_rows(run, rows, on_progress=None):
    # 先跑确定性扫描，抓到的直接算数，不依赖模型
    hard = _polarity_scan(rows)
    for r, why in hard:
        run.note("✗ 极性反转：「%s」-> 「%s」（%s）" % (r["text"], (r.get("reply") or "")[:24], why))
    # 带上音箱位置：不给它这个，「在主卧说开灯、开了北阳台的灯」这类
    # 房间错位它根本无从判断——字面上「开灯」确实答了「灯开了」。
    def _n(r):
        # 实际执行了几步。场景类请求只落一步，往往说明「一整套」被做成了「一件事」，
        # 而字面上完全看不出来——问睡觉、答「主卧灯关了」，读着是通顺的。
        d = r.get("did") or r.get("steps") or []
        return len(d) if isinstance(d, (list, tuple)) else 0
    lines="\n".join(
        '%d. [音箱在%s] 问「%s」-> 答「%s」（实际执行 %d 步）'
        % (i, r.get("room") or "位置未知", r["text"], r["reply"], _n(r))
        for i,r in enumerate(rows))
    import cc
    try:
        v=cc.run_json(
            "下面是智能家居助手的问答记录。请只挑出**答非所问**的：\n"
            "用户问的某个具体东西，回答里压根没有它（比如问甲醛、答温湿度）。\n\n"
            "**你可以用 ./probe.sh 去 HASS 里查证**：用户问的那个东西家里到底有没有、"
            "回答里报的是不是同一个房间的设备。别只看字面——"
            "「阳台有温度计吗」答了客厅和主卧的温度，字面看像答了，其实答非所问。\n\n"
            "**「一整套」被做成「一件事」也算问题**：用户说的是「我要睡了」「我回来了」"
            "「我出门了」这类一句话触发一整套的请求，却只执行了 1 步（比如只关了一盏灯），"
            "那就是问题 —— 哪怕那一步本身没做错、回答也读得通。\n"
            "这一类的 missing **不许出现任何具体设备名**——不许写「灯」「窗帘」"
            "「热水器」这类词，只许写成「这一整套里除了已做的那 N 步之外的部分」"
            "加上实际做了什么（例：「睡前该做的其余动作，实际只执行了回家场景、"
            "把进门灯和过道灯打开了」）。\n"
            "为什么卡这么死：家里睡觉到底关哪些、留哪些，只有住在这儿的人知道"
            "（有人夜里起夜，过道灯就得留着）。你凭常识猜出来的清单会被下游"
            "当成需求实现下去，猜错了没人拦得住。缺口报出来就行，清单等人来写。\n"
            "**操作错房间也算问题**：用户没点名房间时，动的应该是音箱所在房间的设备。\n"
            "在主卧说「开灯」却开了北阳台或客厅的灯，是问题——"
            'missing 写「主卧的灯（开成了北阳台灯）」这种形式。\n'
            "用户自己点名了房间的（「开客厅灯」而音箱在主卧），按点名的算，不是问题；\n"
            "标了「位置未知」的那几条，不要判房间问题。\n\n"
            "不算问题的情况，别报：\n"
            "- 回答简短但确实答了（音箱在客厅、说「开灯」、答「客厅灯开了」是合格回答）\n"
            "- 执行类指令回一句确认语\n"
            "- 回答里已明确说了做不到\n\n"
            "【记录】\n"+lines+
            '\n\n只输出有问题的：[{"i":序号,"missing":"用户要而回答里没有的那个东西"}]，没有输出 []',
            timeout=600, note=run.note, default=None, on_progress=on_progress)
        if v is None:
            run.note("回答质检没拿到结果，本轮跳过"); return []
    except Exception as e:
        run.note("回答质检跳过：%s" % e); return []
    # 保留"缺什么"——分类那步要用它说清「为什么答成那样」。
    # 只返回文本的话，那个信息在这儿就丢了。
    bad=[{"text": r["text"], "missing": why} for r, why in hard]
    for it in v:
        i=it.get("i")
        if isinstance(i,int) and 0<=i<len(rows):
            r=rows[i]
            run.note("✗ 答非所问：「%s」缺 %s" % (r["text"], it.get("missing") or "?"))
            bad.append({"text": r["text"], "missing": it.get("missing") or ""})
    if bad:
        run.metric("答非所问", len(bad), "条", "指标上看是成功的，只有复核才抓得到")
    else:
        run.note("回答质量未见异常")
    return bad


CORR = BASE/"corrections.jsonl"


# review_corrections 已移除（2026-09-04，连同连续对话/纠正一起）。
# 没有纠正入口了，corrections.jsonl 不会再产生。

PROPOSALS  = BASE / "cap_proposals.jsonl"
REGISTER_Q = BASE / "register_queue.json"

def absorb_proposals(run):
    """L3 直连操作过、但能力表里没登记的设备 -> 整理成登记队列。

    main 一直在调这个函数，但它从来没被定义——daily loop 跑到这一阶段
    直接 NameError，后面「补种 L1」「质检已学标注」「学习 + 重训」三个阶段
    全都执行不到。补上。

    为什么这一步重要：L3 走 call_service 那条路绕过了能力表上挂着的全部
    安全检查（极性、房间、二次确认、undo），它只该是临时通道。用过一次就
    该被登记，下次走 L1/L2 的正规路径——否则它会变成一个越用越慢、
    且没有任何护栏的后门（l3_tools 的模块注释里也是这个意思）。

    **只整理和报告，不自动写 capabilities.md / bindings.py**：实体对不对、
    中文名叫什么、要不要二次确认，都得人过一遍。理由和 audit_registry 一样——
    漏登记会张冠李戴，乱登记会稀释模型注意力。
    """
    if not PROPOSALS.exists():
        run.note("还没有 L3 直连设备的记录"); return 0
    known = {c.get("entity") for c in CAPS.values() if c.get("entity")}
    agg = {}
    for line in PROPOSALS.read_text("utf-8").splitlines():
        try: r = json.loads(line)
        except Exception: continue
        eid = r.get("entity_id")
        if not eid or eid in known: continue        # 已经登记过了，不用再提
        a = agg.setdefault(eid, {"entity_id": eid, "hits": 0, "services": [], "texts": []})
        a["hits"] += 1
        sv = r.get("service")
        if sv and sv not in a["services"]: a["services"].append(sv)
        t = r.get("text")
        if t and t not in a["texts"]: a["texts"].append(t)
    if not agg:
        run.note("没有待登记的设备（L3 直连过的都已登记）"); return 0
    rows = sorted(agg.values(), key=lambda x: -x["hits"])
    REGISTER_Q.write_text(json.dumps(rows, ensure_ascii=False, indent=2), "utf-8")
    run.metric("待登记设备", len(rows), "个", "L3 绕过能力表直连过——用过就该登记")
    for a in rows[:5]:
        run.note("· %s（%d 次）例句：%s" % (a["entity_id"], a["hits"], (a["texts"] or [""])[0][:26]))
    run.note("下一步：登进 capabilities.md + bindings.py，再跑 new_cap.py <id> 补说法")
    return len(rows)

def seed_new_caps(run):
    """新增能力后，把它的**能力名**种进 L1。

    L1 最初是 bootstrap 用能力名批量种的（store["l1"][c["name"]] = aid），
    但 bootstrap 只在冷启动跑一次。后来手工加的能力没人补种，结果就是
    能力登记好了、执行也没问题，可说它的标准名字反而要走 L3——
    实测「开次卧灯」1.7 秒，而它本该是 0ms 的精确命中。

    只种 new_caps.json 里登记的。**不要**把 CAPS 里所有缺的名字都补回去：
    「打开空调」这类泛化名是 audit_l1 特意删掉的（家里 3 台空调，写死到
    客厅那台，夜里在卧室说会开客厅的白吹一晚），补回去等于把审计白干。
    """
    nc = BASE/"new_caps.json"
    if not nc.exists(): return 0
    import agent as _A
    from capabilities import CAPS as _C
    store = json.loads(STORE.read_text("utf-8"))
    added = []
    for aid in json.loads(nc.read_text("utf-8")):
        c = _C.get(aid)
        if not c: continue
        name = c["name"]
        if name in store["l1"]: continue
        if _A.polarity_conflict(name, aid) or _A.room_conflict(name, aid):
            run.note("跳过（护栏）：「%s」-> %s" % (name, aid)); continue
        store["l1"][name] = aid; added.append(name)
    if added:
        save_json(STORE, store)
        run.metric("补种 L1", len(added), "条", "、".join(added))
    return len(added)


def audit_poison(run):
    """质检已学标注，抓被固化的错误（Claude）。

    **L1 必须一起查。** 它是精确匹配词典、conf=1.0、优先级最高，
    却曾经三道关全漏：质检只看 examples、考卷把纠正写进去当标准答案、
    collect 只捞低置信度的所以 L1 永远不被复查。实际后果是词典里躺着
    「关灯 -> light_living_on」，说关灯真去开灯，考一万遍也考不出来。
    """
    store=json.loads(STORE.read_text("utf-8"))
    # 先跑一遍不花钱的极性检查——字面说关却标成开，不需要大模型也能判
    import agent as _A
    hard=[(k,v) for k,v in store["l1"].items()
          if _A.polarity_conflict(k,v) or _A.room_conflict(k,v)]
    for k,v in hard:
        why = "极性相反" if _A.polarity_conflict(k,v) else "房间不符"
        run.note("✗ L1 %s：「%s」-> %s，删除" % (why,k,v))
        store["l1"].pop(k,None)
        store["examples"]=[e for e in store["examples"] if e["text"]!=k]
    if hard:
        save_json(STORE, store)
        run.metric("L1 毒数据", len(hard), "条", "最高优先级、原来没人查")
    ex=[{"text":k,"action":v,"_l1":True} for k,v in store["l1"].items()] + store["examples"][-120:]
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
            if tgt.get("_l1") and store["l1"].get(tgt["text"])==tgt["action"]:
                run.note("✗ L1 「%s」%s -> %s" % (tgt["text"],tgt["action"],it["correct"]))
                store["l1"][tgt["text"]]=it["correct"]; n+=1
            for e in store["examples"]:
                if e["text"]==tgt["text"]:
                    run.note(f"✗ 「{e['text']}」{e['action']} -> {it['correct']}")
                    e["action"]=it["correct"]; n+=1
    if n:
        save_json(STORE, store)
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
        ok,_ = SP.add(store, e["text"], e["action"], src=e.get("src") or "daily")
        if ok: seen.add(e["text"]); added += 1
    if added:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy(STORE, MODELS/f"store-{stamp}.bak.json")
        save_json(STORE, store)
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
        collect_multi(r)
    new=[]; unresolved=[]
    if cand:
        with run.stage("标注", "大模型当老师") as r:
            new, unresolved = label(r, cand)
    with run.stage("回答质检", "抓答非所问——指标看着正常，其实没答上") as r:
        bad_answers = audit_answers(r)
    with run.stage("能力缺口", "大模型也搞不定的：分类、攒证据、够了才找人") as r:
        import gaps
        # 两个来源汇到一起：压根没接住的 + 接住了但没答上的
        # 两类分开传给 classify，因为要做的事不一样：
        #   没接住 / 如实说做不到 -> 缺能力
        #   答非所问             -> 能力在，坏在数据源或判定规则
        missed = list(dict.fromkeys(list(unresolved) + collect_unsupported(r)))
        found = (gaps.classify(r, missed, bad_answers=bad_answers)
                 if (missed or bad_answers) else [])
        gs = gaps.merge(r, found)
        gs = gaps.check_done(r)          # 人做完了？系统自己发现
        gaps.notify(r, gs)
        # 攒够证据的推成 GitHub issue。**这步以前漏了**——推送脚本只手动跑过一次，
        # 后面攒的 38 条一条都没推，全躺在本地 json 里。
        try:
            sys.path.insert(0, str(BASE / "loop"))
            import push_gaps
            push_gaps.main(dry=False)
        except Exception as e:
            r.note("推 issue 失败（不影响本轮）：%s" % e)

    with run.stage("登记 L3 用过的设备", "用过一次就该被登记，下次走 0ms 的正规路径") as r:
        absorb_proposals(r)
    with run.stage("补种 L1", "新增能力的标准名字，本该 0ms 命中") as r:
        seed_new_caps(r)
    with run.stage("质检已学标注", "抓被固化的错误") as r:
        audit_poison(r)
    with run.stage("学习 + 重训小模型", "并入新样例，重训 0.6B，考卷不许变差才准换") as r:
        promoted, b, a = learn_and_retrain(r, new)
    run.finish(promoted=promoted, before=b, after=a, learned=len(new))

if __name__=="__main__": main()
