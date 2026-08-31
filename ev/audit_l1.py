# -*- coding: utf-8 -*-
"""审计 L1 精确规则表 —— 系统里最危险的一层。
L1 优先级最高、0ms、无置信度因而不会弃权：一条错的规则 = 永久性、无人复核的毒。
用 Claude 逐条复核（离线任务，L1 很小，很便宜）。
"""
import json, pathlib, sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import llm
from capabilities import CAPS, action_list_for_teacher
from understand import HOME_CTX, STORE

def audit():
    store = json.loads(STORE.read_text("utf-8"))
    l1 = store["l1"]
    if not l1: return []
    lines = "\n".join(f'{i}. 「{k}」 -> {v}（{CAPS.get(v,{}).get("name","??未知动作")}）'
                      for i,(k,v) in enumerate(l1.items()))
    prompt = f"""{HOME_CTX}
你在审计一个家庭语音助手的【精确规则表】。这张表优先级最高、命中就直接执行，
不会再问大模型，也没有置信度可以弃权 —— **一条错的规则会永久生效且无人察觉**。

【全部可用动作】
{action_list_for_teacher()}

【待审的规则表】（用户原话 -> 映射到的动作）
{lines}

逐条判断有没有问题。要特别警惕这几类：
1. **张冠李戴**：映射到了错误的设备/房间（家里有 3 台空调、多套窗帘、多个房间的灯）
2. **过度泛化**：用户说的是笼统说法（如"打开空调"），却被写死到某个具体房间，
   在别的房间说这句话就会开错。这类**建议删除**，让它每次走大模型按上下文判断
3. **动作反了**：开写成关、查询写成执行
4. **指向不存在的动作 id**

只输出 JSON 数组，没问题的不要列出来：
[{{"text":"原话","current":"当前动作","verdict":"wrong|too_broad","correct":"正确动作id或null","why":"一句话"}}]
如果全都没问题，输出 []
"""
    return llm.parse_json(llm.smart(prompt, timeout=300)), l1

def apply(issues):
    store = json.loads(STORE.read_text("utf-8"))
    removed=fixed=0
    for it in issues:
        t=it.get("text")
        if t not in store["l1"]: continue
        if it.get("verdict")=="too_broad" or not it.get("correct"):
            del store["l1"][t]; removed+=1
        elif it["correct"] in CAPS:
            store["l1"][t]=it["correct"]; fixed+=1
    STORE.write_text(json.dumps(store,ensure_ascii=False,indent=2),"utf-8")
    return removed, fixed

if __name__=="__main__":
    issues, l1 = audit()
    print(f"L1 共 {len(l1)} 条，Claude 判定有问题的 {len(issues)} 条：\n")
    for it in issues:
        print(f'  ✗ 「{it.get("text")}」-> {it.get("current")}  [{it.get("verdict")}]')
        print(f'     {it.get("why")}')
        print(f'     处理：{"改为 "+it["correct"] if it.get("correct") else "删除（让它走大模型按上下文判断）"}\n')
    if issues and "--apply" in sys.argv:
        r,f = apply(issues)
        print(f"已处理：删除 {r} 条，修正 {f} 条")
    elif issues:
        print("加 --apply 执行处理")
