# -*- coding: utf-8 -*-
"""执行层：拿到意图 -> 真干活 -> 生成给人听的回答。"""
import re
import resources as R
from capabilities import CAPS, KIND_CONTROL, KIND_QUERY, KIND_SCRIPT, KIND_SCENE, device_of

def _num(v):
    try: return float(v)
    except Exception: return None

def _judge_air(vals, wx):
    """派生判断：适不适合开窗 / 空气怎么样（没有这种现成读数，用已有传感器组合）"""
    t  = _num(vals.get("客厅温度")); h = _num(vals.get("客厅湿度"))
    # 室内室外两个 PM2.5 要分开：开不开窗看的是外面，屋里干不干净看的是里面。
    # 原来只有一个标签「PM2.5」，绑的是和风天气（室外），判断却写成了通用的。
    pm_in  = _num(vals.get("室内PM2.5"))
    pm_out = _num(vals.get("室外PM2.5"))
    qlty   = vals.get("空气质量")
    ot = _num(wx.get("temp")) if wx.get("ok") else None
    bits, advice = [], []
    if t is not None: bits.append(f"客厅 {t}℃")
    if h is not None: bits.append(f"湿度 {h}%")
    if pm_in is not None: bits.append(f"室内 PM2.5 {pm_in}")
    if pm_out is not None:
        bits.append(f"室外 PM2.5 {pm_out}" + (f"（{qlty}）" if qlty else ""))
    if wx.get("ok"): bits.append(f"室外 {wx['temp']}℃ {wx['cond']}")
    # 体感：温度高 + 湿度高 = 黏腻
    if t is not None and h is not None:
        if t >= 27 and h >= 60: advice.append("有点潮热")
        elif h < 35: advice.append("偏干")
        else: advice.append("还行")
    # 适不适合开窗
    if pm_out is not None and pm_out > 75: advice.append("外面 PM2.5 偏高，先别开窗")
    elif wx.get("ok") and "雨" in wx.get("cond",""): advice.append("外面在下雨，开窗注意飘雨")
    elif ot is not None and t is not None and abs(ot - t) >= 8:
        advice.append(f"内外温差 {abs(round(ot-t))}℃，开窗会明显换温")
    else: advice.append("可以开窗透透气")
    return "，".join(bits) + "。" + "；".join(advice) + "。"

# 明确指向「不是现在」的说法。通勤只能按当前路况算，问到未来时段必须说清楚，
# 不能拿现在的数字顶上——用户听到一个像模像样的分钟数，不会知道问题被丢了。
_FUTURE_PAT = re.compile(
    r"明天|后天|大后天|下周|下星期|周[一二三四五六日天]|星期[一二三四五六日天]|"
    r"早高峰|晚高峰|高峰期|上下班点|"
    r"\d{1,2}\s*[:：]\s*\d{2}|\d{1,2}\s*点|待会|等会|一会儿|过会|晚点|稍后")
_NOW_PAT = re.compile(r"现在|此刻|这会|当下|马上|立刻|这就")

def asks_future(text):
    """这句话问的是不是「不是现在」的时段。带『现在』就按现在算。"""
    t = text or ""
    if _NOW_PAT.search(t): return False
    return bool(_FUTURE_PAT.search(t))


def execute(action, dry_run=False, confirmed=False, who=None, text=""):
    """返回 {ok, reply, detail}。需确认的能力(如门禁)必须 confirmed=True 才真执行。"""
    cap = CAPS.get(action)
    if not cap: return {"ok": False, "reply": "这个我还不会", "detail": f"unknown:{action}"}
    if cap.get("confirm") and not confirmed:
        return {"ok": True, "need_confirm": True, "action": action,
                "reply": f"确认要{cap['name']}吗？说「确认」我就执行。",
                "device": device_of(action) or cap["name"], "detail": "waiting_confirm"}
    k = cap["kind"]

    if k == KIND_CONTROL:
        r = R.hass_call(cap["service"], {"entity_id": cap["entity"]}, dry_run)
        ok = "ERR" not in r
        return {"ok": ok, "reply": cap.get("reply", cap["name"]) if ok else "没执行成功",
                "device": device_of(action) or cap["name"], "entity": cap["entity"],
                "service": cap["service"], "detail": r}

    if k == KIND_QUERY:
        if cap.get("state_query"):
            # 按设备类型过滤 —— 问「哪些灯还开着」就只查灯，别把摄像头新风都报出来
            want = cap.get("filter")          # None = 全部
            seen={}
            for aid,c in CAPS.items():
                if c.get("kind")!=KIND_CONTROL or not c.get("entity"): continue
                d=device_of(aid) or c["name"]
                if want and not any(k in d for k in want): continue
                if d not in seen: seen[d]=c["entity"]
            vals=R.read_states(list(seen.items()))
            on=[k2 for k2,v in vals.items() if v=="on"]
            label = cap.get("label","设备")
            txt = (f"开着的{label}：" + "、".join(on)) if on else f"现在没有开着的{label}"
            return {"ok": True, "reply": txt, "device": f"查了 {len(vals)} 个{label}",
                    "detail": {"on":on,"off":[k2 for k2,v in vals.items() if v=="off"]}}
        vals = R.read_states(cap.get("sensors", []))
        if action == "air_quality":
            wx = R.script_weather()
            return {"ok": True, "reply": _judge_air(vals, wx), "device": "客厅/主卧温湿度计+和风天气", "detail": vals}
        if action == "who_home":
            zh = {"home":"在家","not_home":"不在家","work":"在公司","unknown":"不清楚"}
            txt = "，".join(f"{k}{zh.get(v,v)}" for k,v in vals.items())
            return {"ok": True, "reply": txt, "detail": vals}
        unit = "℃" if action=="temperature" else "%"
        good = {k:v for k,v in vals.items() if _num(v) is not None}
        if not good: return {"ok": False, "reply": "传感器现在读不到", "detail": vals}
        return {"ok": True, "reply": "，".join(f"{k} {v}{unit}" for k,v in good.items()), "detail": vals}

    if cap.get("kind") == "needs_room":
        # 走到这儿说明就近改写没成功（音箱没设位置）。
        # **不许兜到某个房间**——那正是原来的毛病。如实问一句。
        return {"ok": False, "reply": cap.get("reply") or "你在哪个房间？",
                "device": cap.get("device"), "needs_room": True}

    if k == KIND_SCRIPT:
        fn = R.SCRIPTS.get(cap["script"])
        if cap["script"] == "music":
            d = fn(dry_run)
        elif cap["script"] == "commute":
            d = fn(who)          # 通勤要按人算，其余脚本不关心是谁
        else:
            d = fn()
        if not d.get("ok"): return {"ok": False, "reply": "查不到，接口出错了", "detail": d}
        if cap["script"]=="commute":
            tip = f"现在开车到{d['label']}大概 {d['minutes']} 分钟，{d['km']} 公里"
            if d.get("taxi_yuan"): tip += f"，打车约 {d['taxi_yuan']} 元"
            if asks_future(text):
                # 百度的未来路况预测（departure_time）是高级付费接口，当前 ak 没开通，
                # 传了也会被静默忽略——实测明天 3 点/9 点/22 点返回同一个数字。
                # 所以这里只能如实说，不能把当前路况当成预测给出去。
                tip = (f"未来时段的路况我算不了，只能按现在的算：到{d['label']}"
                       f"大概 {d['minutes']} 分钟，{d['km']} 公里")
                d = dict(d, only_now=True)
            return {"ok": True, "reply": tip, "device": "百度地图", "detail": d}
        if cap["script"] in ("volume_up","volume_down"):
            return {"ok": True, "reply": f"音量调到 {d['to']}%", "device":"音箱音量", "detail": d}
        if cap["script"]=="music_pause":
            return {"ok": True, "reply": f"{d['action']}了", "device":"音箱", "detail": d}
        if cap["script"]=="music_next":
            return {"ok": True, "reply": "切下一首", "device":"音箱", "detail": d}
        if cap["script"]=="ac_temp_unsupported":
            return {"ok": True, "reply": "家里空调只接了开关，调不了温度——只能开或关。要我关掉吗？",
                    "device":"空调", "detail": d}
        if cap["script"]=="weather":
            return {"ok": True, "reply": f"外面 {d['temp']}℃，{d['cond']}，湿度 {d['humidity']}%", "detail": d}
        return {"ok": True, "reply": "开始播放", "detail": d}

    if k == KIND_SCENE:
        done, fail = [], []
        for step in cap["steps"]:
            r = execute(step, dry_run)
            (done if r["ok"] else fail).append(CAPS[step]["name"])
        devs=[device_of(x) or CAPS[x]["name"] for x in cap["steps"]]
        reply = cap.get("reply","好了")
        if fail: reply += f"（{ '、'.join(fail) }没成功）"
        return {"ok": not fail, "reply": reply, "device": "、".join(devs),
                "steps": cap["steps"], "detail": {"done":done,"fail":fail}}

    return {"ok": False, "reply": "不支持的能力类型", "detail": k}
