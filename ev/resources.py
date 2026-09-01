# -*- coding: utf-8 -*-
"""真实资源访问层：HASS 读/写、外部接口脚本。"""
import json, subprocess, urllib.request, urllib.parse, pathlib, os

def _load_env():
    f = pathlib.Path(__file__).parent.parent / ".env"
    if not f.exists(): return
    for line in f.read_text("utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
_load_env()

HASS_BIN = os.environ.get("EV_HASS_BIN", "/home/hy/code/hass-agent/bin/hass")
BAIDU_AK  = os.environ.get("EV_BAIDU_AK", "")   # 百度地图 ak，放 .env
HOME_ADDR = os.environ.get("EV_HOME_ADDR", "北京市朝阳区望京")
WORK_ADDR = os.environ.get("EV_WORK_ADDR", "北京市朝阳区望京SOHO")

def _hass(*args, timeout=15):
    try:
        r = subprocess.run([HASS_BIN, *args], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() or r.stderr.strip()
    except Exception as e:
        return f"ERR {e}"

def hass_get(entity_id):
    return _hass("get", entity_id)

def hass_tpl(tpl):
    return _hass("tpl", tpl)

def hass_call(service, data: dict, dry_run=False):
    if dry_run:
        return f"[dry-run] {service} {json.dumps(data,ensure_ascii=False)}"
    return _hass("call", service, json.dumps(data, ensure_ascii=False))

def read_states(pairs):
    """pairs: [(label, entity_id)] -> {label: value}，一次模板渲染搞定，省往返"""
    if not pairs: return {}
    tpl = "|".join("{{ states('%s') }}" % e for _, e in pairs)
    out = hass_tpl(tpl)
    vals = out.split("|") if out else []
    res = {}
    for i, (label, _) in enumerate(pairs):
        res[label] = vals[i].strip() if i < len(vals) else "unknown"
    return res

# ---------- 外部脚本 ----------
_geo_cache = {}
def geocode(addr):
    """地名 -> 纬,经（directionlite 只认坐标）"""
    if addr in _geo_cache: return _geo_cache[addr]
    url = ("https://api.map.baidu.com/geocoding/v3/?"
           + urllib.parse.urlencode({"address": addr, "output": "json", "ak": BAIDU_AK}))
    with urllib.request.urlopen(url, timeout=15) as r:
        d = json.loads(r.read())
    if d.get("status") != 0: raise RuntimeError(d.get("message", "geocode failed"))
    loc = d["result"]["location"]
    v = f'{loc["lat"]},{loc["lng"]}'
    _geo_cache[addr] = v
    return v

def script_commute():
    """百度地图算通勤时长（这就是被固化下来的『系统脚本』）"""
    try:
        o, dst = geocode(HOME_ADDR), geocode(WORK_ADDR)
    except Exception as e:
        return {"ok": False, "msg": f"地址解析失败: {e}"}
    url = ("https://api.map.baidu.com/directionlite/v1/driving?"
           + urllib.parse.urlencode({"origin": o, "destination": dst,
                                     "ak": BAIDU_AK, "steps_info": 0}))
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            d = json.loads(r.read())
        if d.get("status") != 0:
            return {"ok": False, "msg": d.get("message", "地图接口出错")}
        rt = d["result"]["routes"][0]
        return {"ok": True, "minutes": round(rt["duration"]/60),
                "km": round(rt["distance"]/1000, 1),
                "from": HOME_ADDR, "to": WORK_ADDR}
    except Exception as e:
        return {"ok": False, "msg": str(e)}

def script_weather():
    out = hass_tpl("{{ state_attr('weather.he_feng_tian_qi_2','temperature') }}|"
                   "{{ states('weather.he_feng_tian_qi_2') }}|"
                   "{{ state_attr('weather.he_feng_tian_qi_2','humidity') }}")
    p = out.split("|")
    zh = {"rainy":"下雨","sunny":"晴","partlycloudy":"多云","cloudy":"阴",
          "snowy":"下雪","fog":"雾","windy":"有风"}
    cond = zh.get(p[1].strip() if len(p)>1 else "", p[1].strip() if len(p)>1 else "未知")
    return {"ok": True, "temp": p[0].strip() if p else "?", "cond": cond,
            "humidity": p[2].strip() if len(p)>2 else "?"}

MUSIC_PLAYER = "media_player.xiaomi_l05c_24fc_play_control"
def script_music(dry_run=False):
    r = hass_call("media_player.media_play", {"entity_id": MUSIC_PLAYER}, dry_run)
    return {"ok": "ERR" not in r, "detail": r, "player": MUSIC_PLAYER}

def _mp(service, data=None, dry_run=False):
    d={"entity_id": MUSIC_PLAYER}; d.update(data or {})
    return hass_call(service, d, dry_run)

def _vol(delta, dry_run=False):
    cur = hass_tpl("{{ state_attr('%s','volume_level') }}" % MUSIC_PLAYER)
    try: v=float(cur)
    except Exception: v=0.2
    nv=max(0.0, min(1.0, round(v+delta, 2)))
    r=_mp("media_player.volume_set", {"volume_level": nv}, dry_run)
    return {"ok":"ERR" not in r, "from":round(v*100), "to":round(nv*100), "detail":r}

def script_volume_up(dry_run=False):   return _vol(+0.15, dry_run)
def script_volume_down(dry_run=False): return _vol(-0.15, dry_run)

def script_music_pause(dry_run=False):
    st = hass_tpl("{{ states('%s') }}" % MUSIC_PLAYER).strip()
    svc = "media_player.media_pause" if st == "playing" else "media_player.media_play"
    r=_mp(svc, None, dry_run)
    return {"ok":"ERR" not in r, "was":st, "action":"暂停" if st=="playing" else "继续", "detail":r}

def script_music_next(dry_run=False):
    r=_mp("media_player.media_next_track", None, dry_run)
    return {"ok":"ERR" not in r, "detail":r}

def script_ac_temp_unsupported(dry_run=False):
    """家里空调只接了开关，调不了温度。如实说，不要拿开/关顶替。"""
    return {"ok": True, "unsupported": True}

SCRIPTS = {"commute": script_commute, "weather": script_weather, "music": script_music,
           "volume_up": script_volume_up, "volume_down": script_volume_down,
           "music_pause": script_music_pause, "music_next": script_music_next,
           "ac_temp_unsupported": script_ac_temp_unsupported}
