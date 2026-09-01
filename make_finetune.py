# -*- coding: utf-8 -*-
"""把训练样例转成 LoRA 微调数据。

关键思路：微调后能力清单被学进权重，**提示词可以从 4168 token 砍到接近 0**。
这才是本地小模型的真正优势——不是模型更聪明，而是任务更窄、上下文更短。

划分严格沿用现有的 train/gate：gate 卷绝不进训练。
"""
import json, pathlib, random, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent / "ev"))
import regression
from understand import STORE

random.seed(7)
BASE = pathlib.Path(__file__).parent
OUT = BASE / "finetune"; OUT.mkdir(exist_ok=True)

# 极简系统提示：只说角色，不列能力（能力靠微调学进去）
SYS = "把用户的话映射到家庭助手的动作 id。只输出 JSON：{\"actions\":[\"<id>\"]}"

def main():
    store = json.loads(STORE.read_text("utf-8"))
    gate = {i["text"] for i in regression.load("gate")}
    seen, rows = set(), []
    for e in store["examples"]:
        t = e["text"]
        if t in gate or t in seen: continue      # 铁律：考卷不进训练
        seen.add(t)
        rows.append({"messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": t},
            {"role": "assistant", "content": json.dumps({"actions": [e["action"]]}, ensure_ascii=False)}]})
    # L1 里的标准说法也是好样本
    for t, a in store["l1"].items():
        if t in gate or t in seen: continue
        seen.add(t)
        rows.append({"messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": t},
            {"role": "assistant", "content": json.dumps({"actions": [a]}, ensure_ascii=False)}]})
    random.shuffle(rows)
    n = len(rows); nv = max(20, n // 12)
    (OUT/"train.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows[nv:]), "utf-8")
    (OUT/"valid.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows[:nv]), "utf-8")
    # 测试集 = 考卷（从未训练）
    test = [{"messages":[{"role":"system","content":SYS},
                         {"role":"user","content":i["text"]},
                         {"role":"assistant","content":json.dumps({"actions":[i["action"]]},ensure_ascii=False)}]}
            for i in regression.load("gate")]
    (OUT/"test.jsonl").write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in test), "utf-8")
    print(f"train {n-nv} / valid {nv} / test(考卷) {len(test)}")
    print(f"系统提示只有 {len(SYS)} 字符（原来 4168 token 的能力清单不再需要）")
    print(f"输出目录 {OUT}")

if __name__ == "__main__": main()
