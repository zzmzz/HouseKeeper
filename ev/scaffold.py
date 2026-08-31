# -*- coding: utf-8 -*-
"""从你家的 HASS 实体自动生成能力清单草稿。

不用手写 capabilities.md 和 bindings.py —— 这两份的初稿由这个脚本产出：
  1. 拉全部可控实体（switch/light/cover/climate/humidifier/media_player）
  2. 去重（同一物理设备常被多个集成暴露两遍）、剔除离线的
  3. 让 Claude 挑出「日常真会说到」的，起中文名、分组、判断需不需要二次确认
  4. 写出 capabilities.md（答案空间）+ bindings.py（执行绑定）

产出是**草稿**，你过一遍再跑 bootstrap。用法：
    python3 scaffold.py [--max 40] [--out-suffix .draft]
"""
import json, os, pathlib, subprocess, sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import llm

HERE = pathlib.Path(__file__).parent
HASS = os.environ.get("EV_HASS_BIN", "/home/hy/code/hass-agent/bin/hass")

SERVICE = {  # 域 -> (开, 关)
 "switch":("switch.turn_on","switch.turn_off"),
 "light":("light.turn_on","light.turn_off"),
 "cover":("cover.open_cover","cover.close_cover"),
 "humidifier":("humidifier.turn_on","humidifier.turn_off"),
 "climate":("climate.turn_on","climate.turn_off"),
}

def pull():
    tpl=("{% for d in ['switch','light','cover','humidifier'] %}{% for e in states[d] %}"
         "{{ e.entity_id }}\t{{ e.name }}\t{{ e.state }}\n{% endfor %}{% endfor %}")
    out=subprocess.run([HASS,"tpl",tpl],capture_output=True,text=True,timeout=90).stdout
    rows=[]
    for ln in out.splitlines():
        p=ln.split("\t")
        if len(p)>=3 and p[1] not in ("None","") and p[2] not in ("unavailable","unknown"):
            rows.append({"entity":p[0],"name":p[1].strip(),"state":p[2]})
    return rows

def dedupe(rows):
    """同一物理设备被多集成暴露：按 friendly_name 归并，保留 entity_id 较短的那个"""
    by={}
    for r in rows:
        k=r["name"].replace(" ","")
        if k not in by or len(r["entity"])<len(by[k]["entity"]): by[k]=r
    return list(by.values())

def ask_claude(rows, max_caps):
    listing="\n".join(f'{r["entity"]}\t{r["name"]}\t{r["state"]}' for r in rows)
    prompt = f"""你在为一个家庭语音助手挑选「值得登记的设备」。

助手只能操作登记过的设备。原则：
- **只登记日常真会用语音说到的**（各房间的灯、空调、新风、窗帘、加湿器、浴霸、热水器、摄像头、门禁…）
- 忽略：车机、手机、纯状态位、功能子开关（如"快烘/除菌/童锁"，只留设备主开关）、明显是测试/冗余的
- 同一设备只登记一次
- 最多 {max_caps} 个设备

【家里的可控实体】（entity_id / 名称 / 当前状态）
{listing}

对每个选中的设备输出：
- id_base：英文小写下划线短标识（如 light_living / ac_bed），**不要**带 _on/_off，脚本会自动补
- name：中文设备名（回答里点名用，如「客厅灯」）
- group：分组，从【灯光/空调 新风/窗帘/水 电器/摄像头 门禁/其它】里选
- both：是否需要同时生成"开"和"关"两个能力（灯/空调等填 true；只开不关的填 false）
- confirm：是否高危需二次确认（门禁类填 true，其余 false）
- use：一句话说明用户什么时候会说它

只输出 JSON 数组，不要解释：
[{{"entity":"...","id_base":"...","name":"...","group":"...","both":true,"confirm":false,"use":"..."}}]
"""
    return llm.parse_json(llm.smart(prompt, timeout=420))

VERB={"灯光":("打开","关闭"),"空调 / 新风":("打开","关闭"),"窗帘":("拉开","拉上"),
      "水 / 电器":("打开","关闭"),"摄像头 / 门禁":("打开","关闭"),"其它":("打开","关闭")}

def emit(picks, suffix=""):
    caps={}; groups={}
    for p in picks:
        dom=p["entity"].split(".")[0]
        on_s,off_s=SERVICE.get(dom,("homeassistant.turn_on","homeassistant.turn_off"))
        g=p.get("group","其它"); vo,vc=VERB.get(g,("打开","关闭"))
        base=p["id_base"]; nm=p["name"]
        on_id=f"{base}_on"
        caps[on_id]=dict(name=f"{vo}{nm}",group=g,use=p.get("use",""),device=nm,
                         kind="hass_control",service=on_s,entity=p["entity"],
                         reply=f"{nm}{'开了' if vo=='打开' else '拉开了'}",
                         confirm=bool(p.get("confirm")))
        groups.setdefault(g,[]).append(on_id)
        if p.get("both"):
            off_id=f"{base}_off"
            caps[off_id]=dict(name=f"{vc}{nm}",group=g,use=f"关掉{nm}。",device=nm,
                              kind="hass_control",service=off_s,entity=p["entity"],
                              reply=f"{nm}{'关了' if vc=='关闭' else '拉上了'}",confirm=False)
            caps[on_id]["undo"]=off_id; caps[off_id]["undo"]=on_id
            groups[g].append(off_id)
    md=["# E.V. 能力清单（答案空间）","",
        "> 由 scaffold.py 从 HASS 实体自动生成的**草稿**。过一遍：删掉用不到的、改中文名、补分组。",
        "> 「辨析」留空即可 —— bootstrap.py 会让 Claude 自动补。",""]
    for g,ids in groups.items():
        md.append(f"## {g}"); md.append("")
        for i in ids:
            c=caps[i]; md.append(f"### {i} · {c['name']}")
            if c["use"]: md.append(f"何时：{c['use']}")
            md.append("")
    (HERE/f"capabilities{suffix}.md").write_text("\n".join(md),"utf-8")
    b=["# -*- coding: utf-8 -*-",'"""执行绑定（scaffold.py 自动生成的草稿）"""','',
       "KIND_CONTROL='hass_control'; KIND_QUERY='hass_query'; KIND_SCRIPT='script'; KIND_SCENE='scene'",'',
       "BINDINGS = {"]
    for i,c in caps.items():
        d={k:v for k,v in c.items() if k in ("kind","service","entity","device","reply","undo") or (k=="confirm" and v)}
        b.append(f"  {i!r}: {d!r},")
    b.append("}")
    (HERE/f"bindings{suffix}.py").write_text("\n".join(b),"utf-8")
    return len(caps), len(groups)

def main():
    mx=40
    if "--max" in sys.argv: mx=int(sys.argv[sys.argv.index("--max")+1])
    sfx=".draft"
    if "--out-suffix" in sys.argv: sfx=sys.argv[sys.argv.index("--out-suffix")+1]
    if "--overwrite" in sys.argv: sfx=""
    print("拉取 HASS 实体…")
    rows=pull(); print(f"  在线可控实体 {len(rows)} 个")
    rows=dedupe(rows); print(f"  去重后 {len(rows)} 个")
    print("让 Claude 挑选值得登记的…（约 1-2 分钟）")
    picks=ask_claude(rows, mx); print(f"  选中 {len(picks)} 个设备")
    n,g=emit(picks,sfx)
    print(f"\n生成 {n} 个能力，{g} 个分组：")
    print(f"  ev/capabilities{sfx}.md")
    print(f"  ev/bindings{sfx}.py")
    print("\n过一遍草稿后改名去掉后缀，再跑：python3 bootstrap.py")

if __name__=="__main__": main()
