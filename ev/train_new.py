# -*- coding: utf-8 -*-
"""给新增能力补训练样例（只补没样例的，不动已有的）"""
import json,pathlib,sys,warnings
warnings.filterwarnings("ignore"); sys.path.insert(0,str(pathlib.Path(__file__).parent))
import llm, regression
from capabilities import CAPS
from understand import STORE, HOME_CTX

PER=18
def main():
    store=json.loads(STORE.read_text("utf-8"))
    have={}
    for e in store["examples"]: have[e["action"]]=have.get(e["action"],0)+1
    gate={i["text"] for i in regression.load("gate")}
    texts={e["text"] for e in store["examples"]}
    todo=[(a,c) for a,c in CAPS.items() if have.get(a,0)<5]
    print(f"需要补样例的能力：{len(todo)} 个 -> {[a for a,_ in todo]}")
    added=0
    for i,(aid,c) in enumerate(todo,1):
        prompt=f"""{HOME_CTX}
为家庭语音助手的这个能力生成用户说法，{PER} 条，口语化、长短不一。

  能力：{aid} — {c['name']}
  什么时候用：{c.get('use','')}
  辨析：{c.get('conflict','')}

**绝对不要**写成其它能力的说法。只输出 JSON 字符串数组。"""
        try:
            for t in llm.parse_json(llm.smart(prompt,timeout=240)):
                if not isinstance(t,str) or not t.strip(): continue
                t=t.strip()
                if t in gate or t in texts: continue
                store["examples"].append({"text":t,"action":aid,"src":"newcap"})
                texts.add(t); added+=1
            print(f"  [{i}/{len(todo)}] {aid} ok", flush=True)
        except Exception as e:
            print(f"  [{i}/{len(todo)}] {aid} 失败 {e}", flush=True)
        STORE.write_text(json.dumps(store,ensure_ascii=False,indent=2),"utf-8")
    print(f"\n新增 {added} 条，样例总数 {len(store['examples'])}")

if __name__=="__main__": main()
