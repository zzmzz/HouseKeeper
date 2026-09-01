# -*- coding: utf-8 -*-
"""理解层：L1 精确 -> L2 本地小模型(带弃权) -> L3 云端大模型(兜底并固化)"""
import json, os, pathlib, re, time, urllib.request, warnings
warnings.filterwarnings("ignore")
import numpy as np
import llm as _LLM
from capabilities import CAPS, action_list_for_teacher

BASE = pathlib.Path(__file__).parent.parent
STORE = BASE / "store.json"
ENVF  = BASE / ".env"

def _env():
    d={}
    for line in ENVF.read_text("utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k,v=line.split("=",1); d[k.strip()]=v.strip()
    return d
ENV=_env()

import datetime as _dt

def _season():
    m=_dt.datetime.now().month
    return {12:"冬天",1:"冬天",2:"冬天",3:"春天",4:"春天",5:"春天",
            6:"夏天",7:"夏天",8:"夏天",9:"秋天",10:"秋天",11:"秋天"}[m]

def _period():
    h=_dt.datetime.now().hour
    if h<5: return "凌晨"
    if h<9: return "早上"
    if h<12: return "上午"
    if h<14: return "中午"
    if h<18: return "下午"
    if h<23: return "晚上"
    return "深夜"

import context as CTX

def home_ctx(state_lines=""):
    return CTX.STATIC + "\n"

HOME_CTX = CTX.STATIC + "\n"   # 静态部分；动态的"此刻"由 runtime_prompt 拼在末尾


_ACTION_LIST=None
def _action_list():
    global _ACTION_LIST
    if _ACTION_LIST is None: _ACTION_LIST=action_list_for_teacher()
    return _ACTION_LIST

GUARD = ("\n\n⚠️重要安全规则：如果用户**点名了某个具体房间/设备**，而清单里没有对应那个房间的动作，"
         "必须返回 action=none，**绝对不要**拿另一个房间的同类设备顶上。"
         '例如用户说"开次卧的灯"，清单里只有客厅灯和主卧灯，就返回 none——'
         "操作错房间的设备比不操作更糟糕。")

_STATIC_PROMPT=None
def teacher_prompt():
    """静态部分：角色 + 家庭常识 + 动作清单 + 规则 + 输出格式。
    动态的『此刻情况』单独拼在最后，保证这一大段前缀稳定、可被 prompt 缓存。"""
    global _STATIC_PROMPT
    if _STATIC_PROMPT: return _STATIC_PROMPT
    _STATIC_PROMPT = ("你是家庭助手的意图识别模块，把用户的话映射到某个动作 id。\n" + HOME_CTX +
            "\n【可用动作】\n" + _action_list() +
            "\n\n先想：主人是在『询问了解』还是『要求执行』？是『热』还是『冷』？是一件事还是一整套？"
            + GUARD +
            '\n\n如果这句话**不属于**上面任何家居能力（闲聊/百科/股票/笑话/音箱自身控制等），'
            '输出 {"actions":["out_of_scope"]} —— 它会被交回给原来的语音助手，这是正确做法。'
            '\n\n用户一句话可能包含多个意图（如「把灯关了顺便开下空调」）。'
            '\n只输出 JSON：{"actions":["<id>", ...]}，按执行顺序排列；'
            '一个意图就一个元素；都不匹配就 {"actions":[]}。不要解释。')
    return _STATIC_PROMPT

def runtime_prompt(room=None):
    """静态提示词 + 此刻的真实情况 + 说话地点（都放最后，保住前缀缓存）"""
    p = teacher_prompt() + "\n\n【此刻】\n" + CTX.now_context() + "\n" + CTX.hint()
    w = CTX.where(room)
    return p + ("\n\n【说话地点】\n" + w if w else "")


META = "meta_correction"
OOS  = "out_of_scope"   # 不是家居指令，交回原助手

def call_llm_ctx(text, last, room=None, timeout=40):
    """带上一轮上下文：一次调用同时判断『是纠正还是新指令』+『该做什么』"""
    from capabilities import CAPS
    sys_p = ("你是家庭助手。判断用户这句话是在【纠正】你上一轮做错的事，还是一条【新指令】。\n"
        + HOME_CTX + "\n【可用动作】\n" + _action_list() +
        '\n\n输出 JSON：{"type":"correction"或"new","actions":["<动作id>",...],"undo":true/false}\n'
        + GUARD + '\ntype=correction 表示在纠正上一轮；undo 表示要不要撤销上一轮那个操作。\n'
        '如果用户只是让你取消/别做了，type=correction、action=none、undo=true。\n'
        '如果是一条全新的指令（哪怕开头有"不对"之类的词），type=new。不要解释。'
        + "\n\n【此刻】\n" + CTX.now_context() + "\n" + CTX.hint()
        + (("\n\n【说话地点】\n" + CTX.where(room)) if room else ""))
    user_p = (f'上一句：「{last["text"]}」\n被理解成：{last.get("action")}'
              f'（{CAPS.get(last.get("action"),{}).get("name","?")}）\n'
              f'实际操作了：{last.get("device","")}\n\n用户现在说：「{text}」')
    body=json.dumps({"model":ENV["EV_MODEL"],"messages":[
        {"role":"system","content":sys_p},{"role":"user","content":user_p}],
        "max_tokens":90,"temperature":0}).encode()
    req=urllib.request.Request(ENV["EV_API_URL"]+"/v1/chat/completions",data=body,
        headers={"Authorization":"Bearer "+ENV["EV_API_KEY"],"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:
            t=json.loads(r.read())["choices"][0]["message"]["content"].strip()
        d=_LLM.parse_json(t)
        acts=d.get("actions") or ([d["action"]] if d.get("action") else [])
        acts=[a for a in acts if a in CAPS]
        return dict(type=d.get("type","new"), action=(acts[0] if acts else None),
                    actions=acts, undo=bool(d.get("undo")))
    except Exception:
        return dict(type="new", action=None, actions=[], undo=False)

def call_llm(text, room=None, timeout=40):
    body=json.dumps({"model":ENV["EV_MODEL"],"messages":[
        {"role":"system","content":runtime_prompt(room)},{"role":"user","content":text}],
        "max_tokens":80,"temperature":0}).encode()
    req=urllib.request.Request(ENV["EV_API_URL"]+"/v1/chat/completions",data=body,
        headers={"Authorization":"Bearer "+ENV["EV_API_KEY"],"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        t=json.loads(r.read())["choices"][0]["message"]["content"].strip()
    try:
        d=_LLM.parse_json(t)
        acts=d.get("actions") or ([d["action"]] if d.get("action") else [])
        if acts and acts[0]==OOS: return None, []       # 不归我管
        acts=[a for a in acts if a in CAPS]
        return (acts[0] if acts else None), acts
    except Exception:
        return None, []

# ---------- 微调小模型（跑在 Mac mini 上，MLX）----------
import os as _os
MLX_URL = _os.environ.get("EV_MLX_URL", "").strip()   # 空 = 不启用，退回 n-gram
_mlx_down_until = 0.0

def mlx_predict(text, timeout=6):
    """调 Mac mini 上的微调 0.6B。返回 (actions列表, ms)，空列表=不确定/不可用。
    服务不可达时短路 60 秒，避免每次请求都干等超时。"""
    global _mlx_down_until
    if not MLX_URL or time.time() < _mlx_down_until:
        return [], 0
    t0=time.time()
    try:
        body=json.dumps({"text":text}).encode()
        req=urllib.request.Request(MLX_URL.rstrip("/")+"/predict", data=body,
                                   headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d=json.loads(r.read())
        acts=[a for a in (d.get("actions") or []) if a in CAPS]   # id 白名单：编造的直接丢弃
        return acts, (time.time()-t0)*1000
    except Exception:
        _mlx_down_until = time.time()+60
        return [], (time.time()-t0)*1000

class Understander:
    def __init__(self, room=None):
        self.room=room
        self.store=json.loads(STORE.read_text("utf-8")) if STORE.exists() else {"l1":{}, "examples":[]}
    def pairs(self):
        return [(t,a) for t,a in self.store["l1"].items()] + \
               [(e["text"],e["action"]) for e in self.store["examples"]]

    def save(self):
        STORE.write_text(json.dumps(self.store,ensure_ascii=False,indent=2),"utf-8")
    # 疑似多意图的连接词：L2 是单标签分类器，遇到这些必须让 L3 拆
    MULTI_HINT = ("顺便","然后","还有","另外","同时","并且","再把","再开","再关","一起")
    # 动词性词根：出现两个以上不同的，多半是多意图
    VERBS = ("开","关","拉","放","调","查","打开","关掉","关闭")

    def looks_multi(self, text):
        # 无分隔符但有多个动词：「开窗帘关灯」
        if len(text) >= 5 and len(self.split_by_verb(text)) >= 2:
            return True
        if len(text) < 6: return False
        if any(k in text for k in self.MULTI_HINT): return True
        # 逗号/顿号分段，且不止一段含动词 -> 多意图
        import re
        segs=[x for x in re.split(r"[，,、；;]", text) if len(x.strip())>=2]
        if len(segs)>=2:
            with_verb=sum(1 for sg in segs if any(v in sg for v in self.VERBS))
            if with_verb>=2: return True
        # "A和B" 形式：和字两边都有设备动词
        if "和" in text or "跟" in text:
            import re as _re
            parts=_re.split(r"[和跟]", text, maxsplit=1)
            if len(parts)==2 and all(len(x.strip())>=2 for x in parts): return True
        return False

    SPLIT_RE = (r"[，,、；;]|\s{2,}|顺便|顺手|然后|还有|另外|同时|并且|以及|"
                r"再把|再开|再关|再拉|一起|也别|也不要|也开|也关|也拉")

    # 无分隔符的连续动词：「开窗帘关灯」「关灯开空调」——口语里很常见，
    # 但没有逗号也没有连接词，靠 SPLIT_RE 切不开。用动词边界补一刀。
    VERB_SPLIT = ("开", "关", "打开", "关掉", "关闭", "拉开", "拉上")

    def split_by_verb(self, text):
        """在第二个及之后的动词前切开。只在没切出多段时兜底用。"""
        import re
        # 找所有动词出现位置（跳过开头那个）
        cuts = []
        for m in re.finditer(r"(开|关|拉)", text):
            i = m.start()
            if i == 0: continue
            if i < 2: continue                    # 太靠前，多半是同一个词
            # 前一个字是动词的一部分（如"打开"）就不切
            if text[i-1] in ("打", "别", "不", "没"): continue
            cuts.append(i)
        if not cuts: return [text]
        segs, prev = [], 0
        for c in cuts:
            seg = text[prev:c]
            if len(seg) >= 2: segs.append(seg); prev = c
        segs.append(text[prev:])
        return [x for x in segs if len(x) >= 2]

    def split_segments(self, text):
        import re
        parts = re.split(self.SPLIT_RE, text)
        # "A和B" 再拆一层（只拆动词性短语，避免拆坏"和风天气"这种）
        out=[]
        for p in parts:
            p=p.strip()
            if not p: continue
            if ("和" in p or "跟" in p) and len(p)>=6:
                sub=re.split(r"[和跟]", p, maxsplit=1)
                if all(len(x.strip())>=2 for x in sub):
                    out+= [x.strip() for x in sub]; continue
            out.append(p)
        return [p for p in out if len(p)>=2]

    OPEN_V  = ("开","打开","开开","亮","启动","来点","放")
    CLOSE_V = ("关","关掉","关上","关闭","灭","停","别开","不用开")

    def _polarity(self, seg):
        """段里有没有明确的开/关动词"""
        has_open  = any(v in seg for v in self.OPEN_V)
        has_close = any(v in seg for v in self.CLOSE_V)
        if has_close: return "close"     # "关"优先，"别开"这类含"开"字但意思是关
        if has_open:  return "open"
        return None

    # 确定性判据：模型学不会、但规则一句话能说清的，直接兜底。
    # 例：查状态时句子里有"灯"就是查灯，不管前面有没有"现在""家里"这些噪音词。
    def rule_fix(self, action, text):
        if action in ("device_state","lights_state"):
            return "lights_state" if "灯" in text else "device_state"
        return action

    # 场景/批量类能力：它们本身就代表"一整套动作"，命中就不该再拆句
    SCENE_KINDS = ("scene",)

    def try_decompose(self, text):
        """多意图：切段后逐段问模型，而不是硬训模型输出数组。

        为什么这么做（查了文献 + 自己踩坑）：
        - 复制少数类样本会过拟合（实测：多意图复制 3 次 -> 单意图 96% 掉到 90%），
          文献也指出 LLM 造少数类数据的通病是"多样性不足"而非数量不足。
        - 模型其实能分清场景 vs 多意图（「关灯拉窗帘我要睡了」正确输出 scene_sleep），
          只是不肯输出多元素数组——96% 的训练样本都是单元素，它把这当成了强先验。
        - 所以：让它先判整句。命中场景/批量能力 -> 就是一个动作，不拆。
          否则切段逐段问——单动作它有 96% 准确率，正是它擅长的。
        """
        segs = self.split_segments(text)
        if len(segs) < 2:
            segs = self.split_by_verb(text)        # 没有分隔符时按动词边界切
        if len(segs) < 2:
            return None
        whole_pol = self._polarity(text)
        out = []
        for sg in segs:
            pol = self._polarity(sg)
            # 「也别落下」「也不要关」这类：字面像关、实际跟着整句走
            if any(w in sg for w in ("也别落下", "别落下", "也不要落下")):
                pol = whole_pol
                sg = ("开" if whole_pol == "open" else "关") + sg.replace("也别落下","").replace("别落下","")
            elif pol is None and whole_pol:                   # 切完丢了动词，补回去
                sg = ("开" if whole_pol == "open" else "关") + sg
            acts, _ = mlx_predict(sg)
            if not acts:
                return None                                   # 有一段拿不准，整句交给 L3
            a = acts[0]
            kind = CAPS.get(a, {}).get("kind")
            if kind in self.SCENE_KINDS:
                return None                                   # 段里冒出场景，说明切错了
            # 一句控制指令被切碎后，残段容易被判成查询/音箱控制（实测拆出过
            # lights_state、music_pause）。这类混进来说明切过头了，整句作废交 L3。
            if kind in ("hass_query",) or a in ("music_pause","music_next","volume_up","volume_down"):
                return None
            if len(out) >= 3:                                 # 一句话超过 3 个动作，多半是切碎了
                return None
            if a not in out:
                out.append(a)
        return out if len(out) >= 2 else None

    def understand(self, text, learn=True, last=None):
        t0=time.time()
        multi = self.looks_multi(text)
        if text in self.store["l1"] and not multi:
            a = self.rule_fix(self.store["l1"][text], text)
            a, moved = CTX.localize(a, text, self.room)     # 就近改写，查表 0ms
            return dict(action=a, actions=[a], layer="L1"+("·就近" if moved else ""),
                        ms=(time.time()-t0)*1000, conf=1.0)
        # L2：微调 0.6B（Mac mini）。id 白名单已在 mlx_predict 里过滤，编造的会返回 None
        macts, mms = mlx_predict(text)
        # 模型只给了一个动作，但句子像多意图，且它给的不是场景类 -> 试着拆
        if macts and len(macts) < 2 and multi and \
           CAPS.get(macts[0], {}).get("kind") not in self.SCENE_KINDS:
            dec = self.try_decompose(text)
            if dec:
                dec = [self.rule_fix(a, text) for a in dec]
                dec = [CTX.localize(a, text, self.room)[0] for a in dec]
                return dict(action=dec[0], actions=dec, layer="L2·模型多",
                            ms=(time.time()-t0)*1000, conf=0.85)
        if macts and not (multi and len(macts) < 2):
            # 多意图：模型直接输出 actions 数组；只出一个但看着像多意图 -> 交给 L3 拆
            macts = [self.rule_fix(a, text) for a in macts]
            moved = False
            out = []
            for a in macts:
                a2, mv = CTX.localize(a, text, self.room); moved = moved or mv; out.append(a2)
            return dict(action=out[0], actions=out,
                        layer="L2·模型" + ("多" if len(out) > 1 else "") + ("·就近" if moved else ""),
                        ms=(time.time()-t0)*1000, conf=0.9)
        act, conf = None, 0.0     # 没有 n-gram 了：MLX 不可用就直接落到 L3
        # 本地拿不准：有上下文就让大模型一次判断"纠正还是新指令"+动作
        if last:
            d=call_llm_ctx(text,last); ms=(time.time()-t0)*1000
            if d["type"]=="correction":
                return dict(action=d["action"], actions=d.get("actions",[]), layer="L3→纠正",
                            ms=ms, conf=conf, is_correction=True, undo=d["undo"])
            if d["action"] and learn:
                self.store["examples"].append({"text":text,"action":d["action"]})
                self.save()   # 同样不重训，见上
            return dict(action=d["action"], actions=d.get("actions",[]), layer="L3", ms=ms,
                        conf=conf, learned=bool(d["action"] and learn))
        a3,acts=call_llm(text)
        ms=(time.time()-t0)*1000
        if a3 and learn:
            # 用户真说过的话 -> examples（走分类器，有置信度、可弃权）
            self.store["examples"].append({"text":text,"action":a3})
            # 注意：大模型编的 canonical 不写进 L1。
            # L1 优先级最高且不会弃权，只应放"出厂种子"和"用户纠正确认过的"，
            # 不能让模型自己往里写——否则错误会永久生效且无人察觉。
            self.save()
            # 注意：这里【不】重训。980 条样例重训一次要 7.6s，会卡死用户等待。
            # 重训是离线蒸馏(distill.py)的活。运行时只负责记录。
        if a3:
            a3 = self.rule_fix(a3, text)
            a3, moved = CTX.localize(a3, text, self.room)
            acts=[CTX.localize(x, text, self.room)[0] for x in acts] or ([a3] if a3 else [])
        return dict(action=a3, actions=acts, layer="L3", ms=ms, conf=conf,
                    learned=bool(a3 and learn), l2_would_say=act)
