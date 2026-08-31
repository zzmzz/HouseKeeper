# -*- coding: utf-8 -*-
"""执行层：拿到意图 -> 真干活 -> 生成给人听的回答。"""
import resources as R
from capabilities import CAPS, KIND_CONTROL, KIND_QUERY, KIND_SCRIPT, KIND_SCENE, device_of

def _num(v):
    try: return float(v)
    except Exception: return None

def _judge_air(vals, wx):
    """派生指标：家里闷不闷 / 适不适合开窗（现成读数里没有，用已有传感器组合）"""
    t  = _num(vals.get("客厅温度")); h = _num(vals.get("客厅湿度"))
    pm = _num(vals.get("PM2.5"));    ot = _num(wx.get("temp")) if wx.get("ok") else None
    bits, advice = [], []
    if t is not None: bits.append(f"客厅 {t}℃")
    if h is not None: bits.append(f"湿度 {h}%")
    if pm is not None: bits.append(f"PM2.5 {pm}")
    if wx.get("ok"): bits.append(f"室外 {wx['temp']}℃ {wx['cond']}")
    # 闷度：温度高 + 湿度高
    if t is not None and h is not None:
        if t >= 27 and h >= 60: advice.append("有点闷")
        elif h < 35: advice.append("偏干")
        else: advice.append("还行")
    # 适不适合开窗
    if pm is not None and pm > 75: advice.append("外面 PM2.5 偏高，先别开窗")
    elif wx.get("ok") and "雨" in wx.get("cond",""): advice.append("外面在下雨，开窗注意飘雨")
    elif ot is not None and t is not None and abs(ot - t) >= 8:
        advice.append(f"内外温差 {abs(round(ot-t))}℃，开窗会明显换温")
    else: advice.append("可以开窗透透气")
    return "，".join(bits) + "。" + "；".join(advice) + "。"

def execute(action, dry_run=False, confirmed=False):
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
            # 遍历所有可控设备，报当前状态
            seen={}
            for aid,c in CAPS.items():
                if c.get("kind")!=KIND_CONTROL or not c.get("entity"): continue
                d=device_of(aid) or c["name"]
                if d not in seen: seen[d]=c["entity"]
            vals=R.read_states(list(seen.items()))
            on=[k2 for k2,v in vals.items() if v=="on"]
            off=[k2 for k2,v in vals.items() if v=="off"]
            txt = ("开着的：" + "、".join(on)) if on else "现在没有开着的设备"
            return {"ok": True, "reply": txt, "device": f"共查 {len(vals)} 个设备",
                    "detail": {"on":on,"off":off}}
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

    if k == KIND_SCRIPT:
        fn = R.SCRIPTS.get(cap["script"])
        d = fn(dry_run) if cap["script"]=="music" else fn()
        if not d.get("ok"): return {"ok": False, "reply": "查不到，接口出错了", "detail": d}
        if cap["script"]=="commute":
            return {"ok": True, "reply": f"现在开车到公司大概 {d['minutes']} 分钟，{d['km']} 公里", "device": "百度地图", "detail": d}
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
