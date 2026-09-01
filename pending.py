# -*- coding: utf-8 -*-
"""哪些交互会进入 daily loop —— 和 daily.collect() 同一套判据，保证所见即所学。"""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent / "ev"))
import regression
from understand import STORE

BASE = pathlib.Path(__file__).parent
TRACES = BASE / "traces.jsonl"

def survey(limit=200):
    if not TRACES.exists():
        return {"total":0, "pending":[], "stat":{}, "gaps":[]}
    store = json.loads(STORE.read_text("utf-8"))
    known = set(store["l1"]) | {e["text"] for e in store["examples"]}
    gate  = {i["text"] for i in regression.load("gate")}

    stat = {"total":0,"l1":0,"l2":0,"l3":0,"corrections":0,"oos":0,"unhandled":0}
    seen, pend = set(), []
    for line in TRACES.read_text("utf-8").splitlines():
        try: r = json.loads(line)
        except Exception: continue
        stat["total"] += 1
        lay = r.get("layer") or ""
        if r.get("event") == "correction": stat["corrections"] += 1
        if lay.startswith("L1"): stat["l1"] += 1
        elif lay.startswith("L2"): stat["l2"] += 1
        elif lay.startswith("L3"): stat["l3"] += 1
        if r.get("out_of_scope"): stat["oos"] += 1
        if not r.get("action") and not r.get("out_of_scope"): stat["unhandled"] += 1

        t = r.get("text")
        if not t or t in seen: continue
        # 和 daily.collect 同一套判据
        if t in known: continue
        if t in gate:  continue
        conf = r.get("conf")
        if lay.startswith("L3") or (conf is not None and conf < 0.6):
            seen.add(t)
            pend.append({"text": t, "layer": lay, "conf": conf,
                         "action": r.get("action"), "reply": r.get("reply"),
                         "ts": r.get("ts"),
                         "why": "大模型兜底过" if lay.startswith("L3") else f"本地没把握 conf={conf}"})
    pend.reverse()
    hit = stat["l1"] + stat["l2"]
    stat["local_rate"] = round(hit / stat["total"] * 100) if stat["total"] else 0
    gaps = []
    gp = BASE / "gaps.json"
    if gp.exists():
        gaps = [g for g in json.loads(gp.read_text("utf-8")) if g.get("status") == "open"]
    return {"total": stat["total"], "stat": stat, "pending": pend[:limit],
            "gaps": [{"title":g["title"],"kind":g["kind"],"hits":g["hits"],
                      "action":g.get("action","")[:200]} for g in gaps]}

if __name__ == "__main__":
    d = survey()
    s = d["stat"]
    print(f"交互 {s['total']} 条 | 本地接住 {s['local_rate']}% "
          f"(L1 {s['l1']} / L2 {s['l2']} / L3 {s['l3']}) | 被纠正 {s['corrections']} 次")
    print(f"\n会进入 daily loop 的 {len(d['pending'])} 条：")
    for p in d["pending"][:30]:
        print(f"  「{p['text']}」  {p['why']}  -> {p['action']}")
    if d["gaps"]:
        print(f"\n未闭合的能力缺口 {len(d['gaps'])} 个：")
        for g in d["gaps"]: print(f"  [{g['kind']}] {g['title'][:50]}（{g['hits']}次）")
