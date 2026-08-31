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
            '\n\n用户一句话可能包含多个意图（如「把灯关了顺便开下空调」）。'
            '\n只输出 JSON：{"actions":["<id>", ...]}，按执行顺序排列；'
            '一个意图就一个元素；都不匹配就 {"actions":[]}。不要解释。')
    return _STATIC_PROMPT

def runtime_prompt():
    """静态提示词 + 此刻的真实情况（放最后）"""
    return teacher_prompt() + "\n\n【此刻】\n" + CTX.now_context() + "\n" + CTX.hint()


META = "meta_correction"

def call_llm_ctx(text, last, timeout=40):
    """带上一轮上下文：一次调用同时判断『是纠正还是新指令』+『该做什么』"""
    from capabilities import CAPS
    sys_p = ("你是家庭助手。判断用户这句话是在【纠正】你上一轮做错的事，还是一条【新指令】。\n"
        + HOME_CTX + "\n【可用动作】\n" + _action_list() +
        '\n\n输出 JSON：{"type":"correction"或"new","actions":["<动作id>",...],"undo":true/false}\n'
        + GUARD + '\ntype=correction 表示在纠正上一轮；undo 表示要不要撤销上一轮那个操作。\n'
        '如果用户只是让你取消/别做了，type=correction、action=none、undo=true。\n'
        '如果是一条全新的指令（哪怕开头有"不对"之类的词），type=new。不要解释。'
        + "\n\n【此刻】\n" + CTX.now_context() + "\n" + CTX.hint())
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

def call_llm(text, timeout=40):
    body=json.dumps({"model":ENV["EV_MODEL"],"messages":[
        {"role":"system","content":runtime_prompt()},{"role":"user","content":text}],
        "max_tokens":80,"temperature":0}).encode()
    req=urllib.request.Request(ENV["EV_API_URL"]+"/v1/chat/completions",data=body,
        headers={"Authorization":"Bearer "+ENV["EV_API_KEY"],"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        t=json.loads(r.read())["choices"][0]["message"]["content"].strip()
    try:
        d=_LLM.parse_json(t)
        acts=d.get("actions") or ([d["action"]] if d.get("action") else [])
        acts=[a for a in acts if a in CAPS]
        return (acts[0] if acts else None), acts
    except Exception:
        return None, []

# ---------- 本地小模型：字符 n-gram + 逻辑回归，带弃权 ----------
def ngrams(s,n=(1,2,3)):
    s=re.sub(r"\s+","",s); o=[]
    for k in n: o+=[s[i:i+k] for i in range(len(s)-k+1)]
    return o

class Student:
    """蒸馏出来的本地小模型。confidence 低于阈值就弃权，交给大模型。"""
    def __init__(self, thresh=0.35):
        self.thresh=thresh; self.clf=None; self.vocab=None; self.labels=None
    def _tf(self, texts):
        M=np.zeros((len(texts),len(self.vocab)),dtype=np.float32)
        for r,t in enumerate(texts):
            for g in ngrams(t):
                j=self.vocab.get(g)
                if j is not None: M[r,j]+=1
        return M/(np.linalg.norm(M,axis=1,keepdims=True)+1e-9)
    def fit(self, pairs):
        from sklearn.linear_model import LogisticRegression
        texts=[t for t,_ in pairs]; acts=[a for _,a in pairs]
        self.labels=sorted(set(acts)); L={a:i for i,a in enumerate(self.labels)}
        v={}
        for t in texts:
            for g in set(ngrams(t)): v[g]=1
        self.vocab={g:i for i,g in enumerate(sorted(v))}
        if len(self.labels)<2: self.clf=None; return self
        self.clf=LogisticRegression(max_iter=3000,C=8.0,class_weight='balanced').fit(self._tf(texts),
                                                             np.array([L[a] for a in acts]))
        return self
    def predict(self, text):
        if self.clf is None: return None, 0.0
        p=self.clf.predict_proba(self._tf([text]))[0]
        i=int(p.argmax()); return self.labels[i], float(p[i])

class Understander:
    def __init__(self, thresh=0.35):
        self.store=json.loads(STORE.read_text("utf-8")) if STORE.exists() else {"l1":{}, "examples":[]}
        self.student=Student(thresh); self.thresh=thresh
        self.retrain()
    def pairs(self):
        return [(t,a) for t,a in self.store["l1"].items()] + \
               [(e["text"],e["action"]) for e in self.store["examples"]]
    def retrain(self, use_cache=True):
        """训练模型。带缓存：数据没变就直接加载，省掉 7-9s。"""
        import hashlib, pickle
        p=self.pairs()
        if not p: return
        sig=hashlib.md5(json.dumps(sorted(p),ensure_ascii=False).encode()).hexdigest()[:12]
        cache=BASE/"models"/f"student-{sig}.pkl"
        if use_cache and cache.exists():
            try:
                with cache.open("rb") as f: self.student=pickle.load(f)
                return
            except Exception: pass
        self.student.fit(p)
        cache.parent.mkdir(exist_ok=True)
        try:
            with cache.open("wb") as f: pickle.dump(self.student,f)
        except Exception: pass
    def save(self):
        STORE.write_text(json.dumps(self.store,ensure_ascii=False,indent=2),"utf-8")
    # 疑似多意图的连接词：L2 是单标签分类器，遇到这些必须让 L3 拆
    MULTI_HINT = ("顺便","然后","还有","另外","同时","并且","再把","再开","再关","一起")
    # 动词性词根：出现两个以上不同的，多半是多意图
    VERBS = ("开","关","拉","放","调","查","打开","关掉","关闭")

    def looks_multi(self, text):
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

    SPLIT_RE = r"[，,、；;]|顺便|然后|还有|另外|同时|并且|再把|再开|再关|一起|以及"

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

    def local_multi(self, text):
        """L2 做多意图：切段逐段分类。
        关键：切完的段可能丢了动词（『开浴霸和热水器』-> 段『热水器』没有"开"），
        所以要把整句的极性补回去，并且极性对不上就弃权交给 L3。"""
        segs=self.split_segments(text)
        if len(segs)<2: return None
        whole_pol=self._polarity(text)
        # 段比整句短、信息少，同样的置信度可信度更低 -> 阈值抬高
        seg_thresh = max(self.thresh + 0.25, 0.65)
        acts=[]
        for sg in segs:
            seg_pol=self._polarity(sg)
            if seg_pol is None and whole_pol:
                sg = ("开" if whole_pol=="open" else "关") + sg     # 补回动词再分类
                seg_pol = whole_pol
            if sg in self.store["l1"]:
                a,c=self.store["l1"][sg],1.0
            else:
                a,c=self.student.predict(sg)
            if not a or a==META or c < seg_thresh:
                return None            # 有一段没把握（含"关灯"这类泛指）-> 整句交给大模型
            # 极性校验：段里说"开"，却判成 *_off（或反之）-> 不可信，交给 L3
            pol = seg_pol or whole_pol
            if pol=="open" and a.endswith(("_off","_close")): return None
            if pol=="close" and a.endswith(("_on","_open")):  return None
            acts.append(a)
        seen=set(); out=[]
        for a in acts:
            if a not in seen: seen.add(a); out.append(a)
        return out if len(out)>=2 else None

    def understand(self, text, learn=True, last=None):
        t0=time.time()
        multi = self.looks_multi(text)
        if multi:
            ml=self.local_multi(text)
            if ml:
                return dict(action=ml[0], actions=ml, layer="L2多",
                            ms=(time.time()-t0)*1000, conf=1.0)
        if text in self.store["l1"] and not multi:
            return dict(action=self.store["l1"][text], layer="L1",
                        ms=(time.time()-t0)*1000, conf=1.0)
        act,conf=self.student.predict(text)
        if act and conf>=self.thresh and not multi:
            # 本地就认出这是"用户在纠正" -> 交给带上下文的大模型解析该改成什么
            if act==META and last:
                d=call_llm_ctx(text,last)
                return dict(action=d["action"], actions=d.get("actions",[]), layer="L2→纠正",
                            ms=(time.time()-t0)*1000, conf=conf, is_correction=True, undo=d["undo"])
            if act==META:
                return dict(action=None, layer="L2", ms=(time.time()-t0)*1000, conf=conf)
            return dict(action=act, layer="L2", ms=(time.time()-t0)*1000, conf=conf)
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
        return dict(action=a3, actions=acts, layer="L3", ms=ms, conf=conf,
                    learned=bool(a3 and learn), l2_would_say=act)
