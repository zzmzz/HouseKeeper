# -*- coding: utf-8 -*-
"""能力注册表 = capabilities.md（答案空间，给模型看）+ bindings.py（执行绑定）

  改「什么时候用 / 辨析」   -> 编辑 capabilities.md，不用动代码
  改「控哪个实体 / 怎么执行」-> 编辑 bindings.py

加载时校验两边 id 一一对应：任何一边漏了都会报错，
结构性地防住"注册表漏登记设备 -> 模型拿相似的顶上"那类事故。
"""
import pathlib, re
from bindings import BINDINGS, KIND_CONTROL, KIND_QUERY, KIND_SCRIPT, KIND_SCENE

MD = pathlib.Path(__file__).parent / "capabilities.md"

def parse_md(path=MD):
    """解析答案空间。格式：## 分组 / ### id · 名字 / 何时：… / 辨析：…"""
    caps, group, cur = {}, "", None
    for line in path.read_text("utf-8").splitlines():
        s = line.strip()
        if s.startswith("## "):
            group = s[3:].strip(); continue
        if s.startswith("### "):
            body = s[4:].strip()
            aid, _, name = body.partition("·")
            cur = aid.strip()
            caps[cur] = {"name": name.strip(), "group": group, "use": "", "conflict": ""}
            continue
        if cur and s.startswith("何时："):  caps[cur]["use"] = s[3:].strip()
        if cur and s.startswith("辨析："):  caps[cur]["conflict"] = s[3:].strip()
    return caps

def build():
    sem = parse_md()
    miss_bind = [a for a in sem if a not in BINDINGS]
    miss_sem  = [a for a in BINDINGS if a not in sem]
    if miss_bind or miss_sem:
        raise RuntimeError(
            f"能力表不一致！\n  md 里有但没绑定: {miss_bind}\n  绑定了但 md 里没有: {miss_sem}\n"
            "  两边 id 必须一一对应。")
    caps = {}
    for aid, s in sem.items():
        caps[aid] = {**BINDINGS[aid], **{k: v for k, v in s.items() if k != "group"},
                     "group": s["group"]}
    return caps

CAPS = build()
DEVICE = {a: c["device"] for a, c in CAPS.items() if c.get("device")}
UNDO   = {a: c["undo"]   for a, c in CAPS.items() if c.get("undo")}

def device_of(aid):
    return DEVICE.get(aid)

def action_list_for_teacher():
    """按分组输出，结构比平铺列表更好读（对模型也一样）"""
    out, last = [], None
    for aid, c in CAPS.items():
        if c.get("group") and c["group"] != last:
            out.append(f"\n【{c['group']}】"); last = c["group"]
        s = f"- {aid}: {c['name']}"
        if c.get("use"): s += f"\n    什么时候用：{c['use']}"
        if c.get("conflict"): s += f"\n    辨析：{c['conflict']}"
        out.append(s)
    return "\n".join(out)
