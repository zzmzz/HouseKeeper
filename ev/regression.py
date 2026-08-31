# -*- coding: utf-8 -*-
"""回归测试：一套固定题目，每次学习后考本地模型，防止越学越坏。
题目来源（三种，越往后越金贵）：
  1) 大模型给每个能力生成的说法
  2) 用户纠正过的（真实、最有价值）
  3) 曾经答错、后来修好的（每个 bug 永久变成一道题）
"""
import json, pathlib, urllib.request, warnings
warnings.filterwarnings("ignore")
from capabilities import CAPS, action_list_for_teacher
from understand import ENV, HOME_CTX, Understander

BASE = pathlib.Path(__file__).parent.parent
SUITE = BASE / "regression_suite.json"

import llm as _LLM

def _llm(msgs, mt=700, temp=0.8, backend="smart"):
    """造回归题目属离线任务 -> 默认走 Claude(smart)，质量更高"""
    sysmsg = next((m["content"] for m in msgs if m["role"]=="system"), "")
    usermsg = next((m["content"] for m in msgs if m["role"]=="user"), "")
    if backend=="smart":
        return _LLM.smart(sysmsg + "\n\n" + usermsg, timeout=300)
    return _LLM.fast(sysmsg, usermsg, max_tokens=mt, temperature=temp)

import hashlib

def assign_split(text, src=None):
    """稳定分卷：train=可用于训练；gate=晋升考卷，永不参与训练。
    用户纠正必须被学会 -> 一律 train。生成的题目按哈希对半分。"""
    if src == "correction": return "train"
    h = int(hashlib.md5(text.encode("utf-8")).hexdigest()[:8], 16)
    return "train" if h % 2 == 0 else "gate"

def load(split=None):
    items = json.loads(SUITE.read_text("utf-8")) if SUITE.exists() else []
    changed=False
    for it in items:
        if "split" not in it:
            it["split"]=assign_split(it["text"], it.get("src")); changed=True
    if changed and items:
        SUITE.write_text(json.dumps(items,ensure_ascii=False,indent=2),"utf-8")
    if split: return [i for i in items if i.get("split")==split]
    return items

def save(items):
    seen=set(); u=[]
    for it in items:
        k=it["text"]
        if k not in seen: seen.add(k); u.append(it)
    SUITE.write_text(json.dumps(u,ensure_ascii=False,indent=2),"utf-8")
    return u

def grow(per=6, only_missing=True):
    """给能力生成题目。only_missing=True 时只补还没题目的能力。"""
    items=load(); have={i["action"] for i in items}; fails=[]
    for aid,c in CAPS.items():
        if only_missing and aid in have: continue
        try:
            out=_llm([{"role":"system","content":
                HOME_CTX+"\n【可用动作】\n"+action_list_for_teacher()+
                f"\n\n为指定动作写 {per} 条这家人真实会说的话，口语化、长短不一。"
                "注意不要写成清单里其它动作的说法（尤其区分开/关、热/冷、询问/执行）。"
                "只输出 JSON 字符串数组。"},
                {"role":"user","content":f"动作：{aid} - {c['name']}\n什么时候用：{c.get('use','')}\n辨析：{c.get('conflict','')}"}])
            for t in _LLM.parse_json(out):
                if isinstance(t,str) and t.strip():
                    items.append({"text":t.strip(),"action":aid,"src":"generated",
                                  "split":assign_split(t.strip(),"generated")})
        except Exception as e:
            fails.append(aid); print(f"  ✗ {aid}: {type(e).__name__} {str(e)[:60]}")
    if fails:
        print(f"  ⚠️ {len(fails)}/{len(CAPS)} 个能力没造出题目：{fails[:8]}")
    return save(items)

def add_case(text, action, src="correction"):
    """用户纠正 / 修好的 bug -> 永久变成一道题"""
    items=load(); items.append({"text":text,"action":action,"src":src,
                                "split":assign_split(text,src)})
    return save(items)

def run(u=None, verbose=True, split=None):
    """只考本地（L1+L2），不许走大模型。split='gate' 时考的是从未训练过的题。"""
    items=load(split)
    if not items:
        print("题库为空，先跑 grow()"); return None
    u = u or Understander()
    ok=0; fails=[]
    for it in items:
        if it["text"] in u.store["l1"]:
            pred=u.store["l1"][it["text"]]; conf=1.0
        else:
            pred,conf=u.student.predict(it["text"])
        if pred==it["action"]: ok+=1
        else: fails.append((it["text"],it["action"],pred,round(conf,2),it.get("src")))
    acc=ok/len(items)*100
    if verbose:
        tag=f"[{split}卷]" if split else "[全部]"
        print(f"回归测试{tag}：{ok}/{len(items)} = {acc:.1f}%")
        by={}
        for it in items: by.setdefault(it.get("src","generated"),[0,0])[1]+=1
        for t,g,p,c,s in fails: by.setdefault(s or "generated",[0,0])
        for t,g,p,c,s in fails[:10]:
            print(f'  ✗ 「{t}」→ {p}(conf {c}) 应为 {g}  [{s}]')
        if len(fails)>10: print(f'  ... 共 {len(fails)} 条失败')
    return {"acc":acc,"ok":ok,"total":len(items),"fails":fails}

if __name__=="__main__":
    import sys
    if "--grow" in sys.argv:
        items=grow(only_missing="--all" not in sys.argv)
        print(f"题库现有 {len(items)} 条")
    run()
