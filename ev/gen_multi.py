# -*- coding: utf-8 -*-
"""造多意图训练数据。

两个要点：
1. 只组合**真实会一起说**的动作（洗澡=浴霸+热水器；出门=关灯+关空调），
   不是随机配对——随机组合出来的句子人根本不会说，学了也没用。
2. **必须造反例**：「关灯拉窗帘睡觉」是一个场景（scene_sleep），不是两个动作。
   不造反例，模型会把所有场景都拆成多个动作。

产出：训练数据进 store，另留一份多意图考卷（不参与训练）。
"""
import json, pathlib, random, sys, warnings
warnings.filterwarnings("ignore"); sys.path.insert(0, str(pathlib.Path(__file__).parent))
import llm, regression
from capabilities import CAPS
from understand import STORE, HOME_CTX

random.seed(11)
BASE = pathlib.Path(__file__).parent.parent
MULTI_TEST = BASE / "multi_test.json"

# 真实会一起说的组合（人工挑，不让模型乱配）
COMBOS = [
 (["bath_heater_on","water_heater_on"],   "洗澡前：开浴霸 + 开热水器"),
 (["light_living_off","ac_off"],          "离开客厅：关灯 + 关空调"),
 (["light_living_on","ac_on"],            "回到客厅：开灯 + 开空调"),
 (["hallway_on","entry_on"],              "进门：开过道灯 + 开进门灯"),
 (["kitchen_on","fresh_air_on"],          "做饭：开厨房灯 + 开新风"),
 (["dining_on","wall_wash_on"],           "吃饭：开餐厅灯 + 开洗墙灯"),
 (["ac_bed_on","bed_curtain_close"],      "睡前主卧：开空调 + 拉窗帘"),
 (["light_living_off","curtain_close"],   "关客厅灯 + 拉纱帘"),
 (["water_heater_on","zero_cold_water_on"],"烧水：开热水器 + 开零冷水"),
 (["camera_living_off","camera_dining_off"],"关两个摄像头（也可能说'监控都关了'=camera_all_off）"),
 (["bath_heater_on","dry_area_on"],       "洗漱：开浴霸 + 开干区灯"),
 (["ac_on","curtain_close"],              "客厅：开空调 + 拉窗帘"),
]

# 反例：听起来像多动作，其实是一个场景/批量能力
SINGLES = [
 ("scene_sleep",     "睡觉场景（关灯+拉窗帘+空调 一整套，说'睡了'触发）"),
 ("scene_home",      "回家场景（进门灯+过道灯 一整套）"),
 ("all_lights_off",  "关掉所有灯（一个批量动作，不是逐个关）"),
 ("all_ac_on",       "打开所有空调"),
 ("all_ac_off",      "关掉所有空调"),
 ("camera_all_off",  "关掉所有摄像头"),
]

def gen_multi(acts, desc, n=14):
    names = " + ".join(CAPS[a]["name"] for a in acts)
    p = f"""{HOME_CTX}
生成用户**一句话同时要求两件事**的说法，{n} 条。

  这两件事：{names}
  场景：{desc}

要求：
- 一句话里明确包含这两个动作，口语化（用「顺便」「再」「和」「，」等连接，也可以省略连接词）
- 长短不一，有的带理由有的不带
- **不要**写成"睡觉""回家"这类整套场景的说法——那是另一个能力

只输出 JSON 字符串数组。"""
    return llm.parse_json(llm.smart(p, timeout=240))

def gen_single(aid, desc, n=12):
    p = f"""{HOME_CTX}
生成用户说法，{n} 条，对应这**一个**动作：

  {aid} — {CAPS[aid]['name']}
  {desc}

★关键：这些话虽然听起来涉及好几个设备，但它是**一个整体动作**，不是拆开的多件事。
比如「关灯拉窗帘我要睡了」就是睡觉场景这一个动作。
请生成这类"听起来像多件事、其实是一个动作"的说法。

只输出 JSON 字符串数组。"""
    return llm.parse_json(llm.smart(p, timeout=240))

def main():
    store = json.loads(STORE.read_text("utf-8"))
    gate = {i["text"] for i in regression.load("gate")}
    have = {e["text"] for e in store["examples"]}
    multi_rows, test_rows = [], []

    print("=== 多意图组合 ===", flush=True)
    for i,(acts,desc) in enumerate(COMBOS,1):
        try:
            texts=[t.strip() for t in gen_multi(acts,desc) if isinstance(t,str) and t.strip()]
        except Exception as e:
            print(f"  [{i}/{len(COMBOS)}] 失败 {e}", flush=True); continue
        random.shuffle(texts)
        k=max(2, len(texts)//4)                 # 1/4 留作考卷
        for t in texts[k:]:
            if t in gate or t in have: continue
            multi_rows.append({"text":t,"actions":acts}); have.add(t)
        for t in texts[:k]:
            if t in gate or t in have: continue
            test_rows.append({"text":t,"actions":acts}); have.add(t)
        print(f"  [{i}/{len(COMBOS)}] {'+'.join(acts)}: 训练 {len(texts)-k} / 考卷 {k}", flush=True)

    print("\n=== 反例（像多件事其实是一个场景）===", flush=True)
    single_rows=[]
    for i,(aid,desc) in enumerate(SINGLES,1):
        try:
            texts=[t.strip() for t in gen_single(aid,desc) if isinstance(t,str) and t.strip()]
        except Exception as e:
            print(f"  [{i}/{len(SINGLES)}] 失败 {e}", flush=True); continue
        for t in texts:
            if t in gate or t in have: continue
            single_rows.append({"text":t,"action":aid,"src":"multi_neg"}); have.add(t)
        print(f"  [{i}/{len(SINGLES)}] {aid}: {len(texts)} 条", flush=True)

    store["examples"] += single_rows
    store["multi"] = store.get("multi", []) + multi_rows      # 多意图单独存
    STORE.write_text(json.dumps(store,ensure_ascii=False,indent=2),"utf-8")
    MULTI_TEST.write_text(json.dumps(test_rows,ensure_ascii=False,indent=2),"utf-8")
    print(f"\n多意图训练 {len(multi_rows)} 条 | 反例 {len(single_rows)} 条 | 多意图考卷 {len(test_rows)} 条")

if __name__=="__main__": main()
