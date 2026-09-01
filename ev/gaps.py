# -*- coding: utf-8 -*-
"""能力缺口：大模型也解决不了、需要人参与的事，怎么 loop 起来。

daily loop 里大模型标不出来的请求，原来直接丢弃。但它们分好几种：

  A 已有实体没登记  -> 自动补（scaffold 能做）
  B 可用现有传感器组合出来 -> 自动补（派生指标）
  C 要买硬件 / 要抓包逆向 / 要动手装 -> **需要人**
  D 压根不该我管 -> 记为 out_of_scope

C 才是这里要解决的。它的 loop 长这样：

    攒证据（同一类需求被问过几次）
      -> 够了才提醒（不够就闭嘴，避免骚扰）
      -> 人去做（买设备 / 抓包 / 装东西）
      -> **系统自己发现做完了**（新实体出现在 HASS / HAR 文件出现在收件箱）
      -> 自动补进能力清单 -> 原来那句话现在能用了 -> 闭环

最后一步是关键：完成信号必须可观测，不能指望人回来打勾。
"""
import json, pathlib, subprocess, sys, time, warnings, datetime
warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import llm
from capabilities import CAPS, action_list_for_teacher
from understand import HOME_CTX

BASE = pathlib.Path(__file__).parent.parent
GAPS = BASE / "gaps.json"
INBOX = BASE / "inbox"          # 人把抓包文件丢这儿
HASS = "/home/hy/code/hass-agent/bin/hass"

MIN_HITS = 3        # 同一类需求被问到几次才值得打扰人
RENOTIFY_DAYS = 7   # 提醒过之后隔多久再提

def load():
    return json.loads(GAPS.read_text("utf-8")) if GAPS.exists() else []

def save(gs):
    GAPS.write_text(json.dumps(gs, ensure_ascii=False, indent=2), "utf-8")

def _today():
    return datetime.date.today().isoformat()

# ---------- 分类：这句话解决不了，是哪一种解决不了 ----------
def classify(run, texts):
    """把大模型标不出来的请求分类，并给出「人要做什么」"""
    if not texts: return []
    listing = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    cap_names = "、".join(c["name"] for c in CAPS.values())
    prompt = f"""{HOME_CTX}
下面这些话，家庭助手的现有能力都处理不了。请判断每条**为什么**处理不了，以及要怎样才能支持。

【现有能力】（只列名字，够判断有没有了）
{cap_names}

【处理不了的请求】
{listing}

对每条判断 kind：
- `hardware`   ：家里缺这个设备/传感器，**得买**（如问 CO2 但没有 CO2 传感器）
- `integration`：设备/服务存在但没接进来，**得抓包或逆向**（如某个 App 控制的设备）
- `derive`     ：不用买，**用现有传感器组合**就能算出来
- `install`    ：设备已有，但需要人动手（装电池、接线、重新配网、开权限）
- `out_of_scope`：本来就不该家庭助手管（闲聊/百科/点外卖）

同类的合并成一条。只输出 JSON 数组：
[{{"kind":"hardware","title":"一句话说清缺什么",
  "why":"为什么现在做不到",
  "action":"**人具体要做什么**，越具体越好（买什么型号/抓哪个 App 的哪个操作）",
  "detect":"做完之后系统怎么自动发现（如：HASS 里出现包含 co2 的新实体 / inbox 里出现 xxx.har）",
  "samples":["原话1","原话2"]}}]
out_of_scope 的不用输出。"""
    try:
        return llm.parse_json(llm.smart(prompt, timeout=600))
    except Exception as e:
        run.note(f"分类失败: {e}")
        return []

# ---------- 累积证据 ----------
def merge(run, found):
    """新发现的缺口并进队列；已存在的累加计数"""
    gs = load()
    by_title = {g["title"]: g for g in gs}
    new = 0
    for f in found:
        t = f.get("title")
        if not t: continue
        if t in by_title:
            g = by_title[t]
            g["hits"] += len(f.get("samples") or [1])
            g["last_seen"] = _today()
            for s in (f.get("samples") or []):
                if s not in g["samples"]: g["samples"].append(s)
        else:
            g = {"id": f"gap-{int(time.time()*1000)%10**8}", "kind": f.get("kind","install"),
                 "title": t, "why": f.get("why",""), "action": f.get("action",""),
                 "detect": f.get("detect",""), "samples": f.get("samples") or [],
                 "hits": len(f.get("samples") or [1]), "status": "open",
                 "first_seen": _today(), "last_seen": _today(), "notified": None}
            gs.append(g); by_title[t] = g; new += 1
    save(gs)
    run.metric("新缺口", new, "个")
    return gs

# ---------- 自动发现「人已经做完了」 ----------
def _hass_entities():
    tpl = ("{% for d in ['sensor','switch','light','cover','climate','humidifier','binary_sensor'] %}"
           "{% for e in states[d] %}{{ e.entity_id }}|{{ e.name }} {% endfor %}{% endfor %}")
    try:
        out = subprocess.run([HASS, "tpl", tpl], capture_output=True, text=True, timeout=60).stdout
        return out.lower()
    except Exception:
        return ""

def _entity_set():
    """当前 HASS 实体 id 集合"""
    tpl = ("{% for d in ['sensor','switch','light','cover','climate','humidifier','vacuum',"
           "'media_player','binary_sensor'] %}{% for e in states[d] %}{{ e.entity_id }}\n"
           "{% endfor %}{% endfor %}")
    try:
        out = subprocess.run([HASS, "tpl", tpl], capture_output=True, text=True, timeout=60).stdout
        return {l.strip().lower() for l in out.splitlines() if l.strip()}
    except Exception:
        return set()

def check_done(run):
    """完成信号可观测：新设备出现在 HASS / 抓包文件出现在 inbox。

    关键：记录**基线**，只认「缺口登记之后新出现的」实体。
    否则会误判 —— 家里本来就有 PM2.5 传感器，找 CO2 时匹配到 pm2 就以为买回来了。
    """
    gs = load()
    if not gs: return gs
    now = _entity_set()
    inbox_files = [p.name.lower() for p in INBOX.glob("*")] if INBOX.exists() else []
    closed = 0
    for g in gs:
        if g["status"] != "open":
            continue
        if not g.get("baseline"):          # 第一次见到这条缺口，先存基线
            g["baseline"] = sorted(now)
            continue
        added = now - set(g["baseline"])   # 只看新增的实体
        hit = False
        if g["kind"] == "integration" and inbox_files:
            hit = any(f.endswith((".har", ".json", ".pcap")) for f in inbox_files)
        if not hit and added:
            hint = (g.get("detect","") + " " + g.get("title","")).lower()
            keys = [w for w in ["co2","carbon_dioxide","hcho","formaldehyde","tvoc","pm25","pm2_5",
                                "vacuum","dishwasher","media_player","balcony","yang_tai",
                                "水浸","门磁","光照","噪音"] if w in hint]
            hit = any(any(k in e for e in added) for k in keys) if keys else False
            if hit:
                run.note(f"   新增实体：{[e for e in added if any(k in e for k in keys)][:3]}")
        if hit:
            g["status"] = "done"; g["done_at"] = _today(); closed += 1
            run.note(f"✅ 缺口已闭合：{g['title'][:40]}")
    save(gs)
    run.metric("自动闭合", closed, "个")
    return gs

# ---------- 提醒（攒够了才说，且不重复骚扰）----------
def to_notify(gs):
    out = []
    for g in gs:
        if g["status"] != "open": continue
        if g["hits"] < MIN_HITS: continue          # 攒够频次才值得打扰
        if g.get("notified"):
            d = (datetime.date.today() - datetime.date.fromisoformat(g["notified"])).days
            if d < RENOTIFY_DAYS: continue         # 提醒过了，冷却期内不再说
        out.append(g)
    return out

KIND_CN = {"hardware":"要买", "integration":"要抓包", "derive":"可派生", "install":"要动手"}

def notify(run, gs):
    todo = to_notify(gs)
    if not todo:
        run.note("没有需要打扰你的缺口")
        return
    lines = [f"[{KIND_CN.get(g['kind'],g['kind'])}] {g['title']}（被问 {g['hits']} 次）\n  → {g['action']}"
             for g in todo]
    body = "\n".join(lines)
    print("\n" + "="*66); print("需要你参与的事："); print("="*66); print(body)
    try:
        subprocess.run(["/home/hy/code/scripts/bark-push.sh",
                        f"E.V. 有 {len(todo)} 件事需要你",
                        body[:1400], "EV能力缺口", "active", "alert"], timeout=30)
        run.note("已推送到手机")
    except Exception as e:
        run.note(f"Bark 推送失败（不影响队列）: {e}")
    for g in todo: g["notified"] = _today()
    save(gs)
    run.metric("提醒", len(todo), "件")

# ---------- CLI ----------
def _print_all():
    gs = load()
    if not gs: return print("暂无缺口记录")
    for g in gs:
        flag = {"open":"○","done":"✅","dismissed":"✕"}.get(g["status"],"?")
        print(f"{flag} [{KIND_CN.get(g['kind'],g['kind'])}] {g['title']}  "
              f"（{g['hits']}次 / {g['first_seen']}~{g['last_seen']}）")
        if g["status"]=="open":
            print(f"    要做：{g['action']}")
            print(f"    完成判定：{g['detect']}")
        if g.get("samples"): print(f"    例句：{g['samples'][0]}")

if __name__ == "__main__":
    if len(sys.argv)>2 and sys.argv[1] in ("done","dismiss"):
        gs=load(); gid=sys.argv[2]
        for g in gs:
            if g["id"]==gid or gid in g["title"]:
                g["status"]="done" if sys.argv[1]=="done" else "dismissed"
                g["done_at"]=_today(); print(f"已标记：{g['title']}")
        save(gs)
    else:
        _print_all()
