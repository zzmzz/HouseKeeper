# -*- coding: utf-8 -*-
"""动态家庭上下文：把"此刻"的真实情况拼给大模型。
解决写死"8月末夏天"的问题——冬天说"有点热"不该判成开空调制冷。

设计要点：
1. 带 TTL 缓存，避免每次 L3 都花 200ms 读传感器
2. 放在提示词【末尾】，让前面的静态动作清单保持可缓存前缀
"""
import datetime, time
import resources as R

_cache = {"ts": 0, "text": ""}
TTL = 90          # 秒。家里环境变化慢，90秒够新鲜了

def _season(m):
    return {12:"冬天",1:"冬天",2:"冬天",3:"春天",4:"春天",5:"春天",
            6:"夏天",7:"夏天",8:"夏天",9:"秋天",10:"秋天",11:"秋天"}[m]

def _daypart(h):
    if h<5:  return "深夜"
    if h<9:  return "早上"
    if h<11: return "上午"
    if h<14: return "中午"
    if h<17: return "下午"
    if h<19: return "傍晚"
    if h<23: return "晚上"
    return "深夜"

STATIC = """【这个家】
北京。房间：客厅、餐厅、主卧、次卧、厨房、玄关过道、卫生间(干/湿区)、阳台。
灯挂在 Aqara 墙壁开关面板上，一个面板多个按键控制不同的灯。
常住两位成人+一只猫，作息不规律，凌晨可能起夜。"""

def now_context(force=False):
    """此刻的真实情况。带缓存。"""
    if not force and time.time()-_cache["ts"] < TTL and _cache["text"]:
        return _cache["text"]
    n = datetime.datetime.now()
    wd = "周" + "一二三四五六日"[n.weekday()]
    head = f"现在：{n.month}月{n.day}日 {wd} {n.hour}点（{_season(n.month)}，{_daypart(n.hour)}）"
    lines = [head]
    try:
        vals = R.read_states([
            ("客厅温度","sensor.miaomiaoce_t2_d817_temperature"),
            ("客厅湿度","sensor.miaomiaoce_t2_d817_relative_humidity"),
            ("主卧温度","sensor.miaomiaoce_t2_18c0_temperature"),
            ("子沫","person.ziiimo"), ("小羽","person.jhy")])
        ind=[]
        for k in ("客厅温度","主卧温度"):
            v=vals.get(k)
            if v and v not in ("unknown","unavailable"): ind.append(f"{k}{v}℃")
        h=vals.get("客厅湿度")
        if h and h not in ("unknown","unavailable"): ind.append(f"客厅湿度{h}%")
        if ind: lines.append("室内：" + "，".join(ind))
        zh={"home":"在家","not_home":"不在家","work":"在公司","unknown":"位置不明"}
        who=[f"{k}{zh.get(vals.get(k),vals.get(k))}" for k in ("子沫","小羽") if vals.get(k)]
        if who: lines.append("人：" + "，".join(who))
    except Exception: pass
    try:
        w = R.script_weather()
        if w.get("ok"): lines.append(f"室外：{w['temp']}℃ {w['cond']}，湿度{w['humidity']}%")
    except Exception: pass
    txt = "\n".join(lines)
    _cache.update(ts=time.time(), text=txt)
    return txt

# 语音端所在房间 -> 该房间的"默认设备"。用户不点名房间时，就近原则。
ROOM_DEFAULTS = {
 "主卧": {"空调":"ac_bed_on/ac_bed_off","灯":"light_bed_on/light_bed_off",
          "新风":"fresh_air_bed_on","窗帘":"bed_curtain_open/bed_curtain_close"},
 "次卧": {"空调":"ac_second_on/ac_second_off","新风":"fresh_air_second_on"},
 "客厅": {"空调":"ac_on/ac_off","灯":"light_living_on/light_living_off",
          "新风":"fresh_air_living_on","窗帘":"curtain_open/curtain_close"},
 "餐厅": {"灯":"dining_on/dining_off"},
 "厨房": {"灯":"kitchen_on/kitchen_off"},
 "玄关": {"灯":"entry_on/entry_off"},
}

def where(room=None):
    """说话地点。用户不点名房间时，笼统指令应该落在这个房间。"""
    if not room: return ""
    lines=[f"⚠️ 用户此刻正在【{room}】对音箱说话。"]
    d=ROOM_DEFAULTS.get(room)
    if d:
        lines.append(f"他没点名房间时（如『打开空调』『把灯关了』『开下新风』），"
                     f"默认就是{room}的那台，不是客厅的：")
        lines += [f"  {k} -> {v}" for k,v in d.items()]
    lines.append(f"只有明确说了别的房间（『客厅空调』『次卧的灯』）才用那个房间的。")
    return "\n".join(lines)

def hint():
    """给模型的判读提示——季节决定『热/冷』的含义"""
    m = datetime.datetime.now().month
    if m in (6,7,8,9):
        return "（夏天：说『热』『闷』是要制冷降温；说『冷』多半是空调开太低要调高温度）"
    if m in (12,1,2,3):
        return "（冬天：说『冷』是要取暖升温；说『热』多半是暖气太足要调低）"
    return "（换季：冷热判断看室内外实际温度）"

if __name__=="__main__":
    print(STATIC); print(); print(now_context()); print(hint())
