# -*- coding: utf-8 -*-
"""用 Claude 体检能力注册表：拿家里真实实体对照，找出「用户可能会说、但注册表里没有」的设备。
这是离线任务，用 smart 后端。对症的正是「开主卧空调却开了客厅」那类事故。
"""
import json, subprocess, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import llm
from capabilities import CAPS

HASS="/home/hy/code/hass-agent/bin/hass"

def real_entities():
    """拉家里可控设备（switch/light/cover/climate/humidifier）的真实名"""
    tpl = ("{% for d in ['switch','light','cover','climate','humidifier'] %}"
           "{% for e in states[d] %}{{ e.entity_id }}\t{{ e.name }}\t{{ e.state }}\n"
           "{% endfor %}{% endfor %}")
    out = subprocess.run([HASS,"tpl",tpl],capture_output=True,text=True,timeout=60).stdout
    rows=[]
    for line in out.splitlines():
        p=line.split("\t")
        if len(p)>=3 and p[1] not in ("None",""): rows.append((p[0],p[1],p[2]))
    return rows

def audit(max_entities=260):
    ents = real_entities()
    # 只看状态正常的（unavailable 的多半是坏的/冗余集成）
    live = [e for e in ents if e[2] not in ("unavailable","unknown")][:max_entities]
    registered = {c["entity"] for c in CAPS.values() if c.get("entity")}
    have = "\n".join(f"- {a}: {c['name']}  [{c.get('entity','')}]"
                     for a,c in CAPS.items() if c.get("entity"))
    pool = "\n".join(f"{e}\t{n}\t{s}" for e,n,s in live if e not in registered)
    prompt = f"""你在给一个家庭语音助手体检"能力注册表"。

背景：助手只能操作注册表里登记的设备。如果用户提到一个**没登记**的设备，
大模型会挑个"最像的"去操作 —— 已经出过事故：说「开主卧空调」结果开了客厅空调。

【已登记的能力】
{have}

【家里还没登记的可控实体】（entity_id / 名称 / 当前状态）
{pool}

请找出**用户日常很可能会说到、但没登记**的设备，按重要性排序。注意：
- 同一物理设备常被多个集成重复暴露（如 lumi_xxx_switch 和 lumi_cn_xxx_on_p_x_x），算一个
- 忽略车机、手机、纯状态类、明显是测试/冗余的
- 重点关注：各房间的灯、空调、新风、窗帘、加湿器、浴霸这类日常会说的

只输出 JSON 数组，最多 12 条：
[{{"entity":"...","name":"...","why":"用户可能会怎么说它","suggest_id":"建议的能力id"}}]
"""
    out = llm.smart(prompt, timeout=300)
    return llm.parse_json(out), len(live), len(registered)

if __name__=="__main__":
    items, n_live, n_reg = audit()
    print(f"家里活跃可控实体 {n_live} 个，已登记 {n_reg} 个\n")
    print(f"Claude 建议补登记 {len(items)} 个：\n")
    for i,it in enumerate(items,1):
        print(f"{i:2}. {it.get('name')}  [{it.get('entity')}]")
        print(f"    用户可能说：{it.get('why')}")
        print(f"    建议 id：{it.get('suggest_id')}\n")
