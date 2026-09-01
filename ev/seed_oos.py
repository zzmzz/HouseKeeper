# -*- coding: utf-8 -*-
"""教本地模型认出「这不是家居指令」。

接到音箱上时至关重要：用户问股票/笑话/百科，E.V. 必须说"我管不了"并交回原来的小爱，
而不是硬塞给某个家居能力（实测「苹果公司市值多少」会以 0.58 置信度判成查通勤）。
"""
import json, pathlib, sys, warnings
warnings.filterwarnings("ignore"); sys.path.insert(0, str(pathlib.Path(__file__).parent))
import llm
from understand import STORE, HOME_CTX

OOS = "out_of_scope"

def gen(n=90):
    out=[]
    for i,topic in enumerate([
        "闲聊、讲笑话、唱歌、聊天说说话",
        "百科问答：历史、科学、名人、公司、地理常识",
        "生活服务：股票基金、限号、快递、外卖、挂号、健康问题",
        "日程提醒、闹钟、倒计时、算数、翻译",
        "音箱自身：调音量、上一首下一首、播放某个具体歌手的歌、听广播新闻"]):
        p=f"""{HOME_CTX}
一个家庭语音助手只管**这个家里的设备控制和环境查询**（开关灯/空调/窗帘/新风/热水器/摄像头/门禁、
查室内温湿度空气、通勤时长、天气、放音乐、睡觉回家场景）。

其它一切都不归它管，要交回给原来的语音助手。

请生成用户会对音箱说、但**不属于**上面那些家居能力的话，{n//5} 条。
本批主题：{topic}

要求口语化、像真人对家里音箱说的。只输出 JSON 字符串数组。"""
        try:
            out += [t.strip() for t in llm.parse_json(llm.smart(p, timeout=240))
                    if isinstance(t,str) and t.strip()]
            print(f"  [{i+1}/5] 累计 {len(out)} 条", flush=True)
        except Exception as e:
            print(f"  [{i+1}/5] 失败: {e}", flush=True)
    return out

if __name__=="__main__":
    store=json.loads(STORE.read_text("utf-8"))
    have={e["text"] for e in store["examples"]}
    n=0
    for t in gen():
        if t not in have:
            store["examples"].append({"text":t,"action":OOS,"src":"oos"}); have.add(t); n+=1
    STORE.write_text(json.dumps(store,ensure_ascii=False,indent=2),"utf-8")
    print(f"\n新增 {n} 条 out_of_scope 样例，样例总数 {len(store['examples'])}")
