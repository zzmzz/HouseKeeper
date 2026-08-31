# -*- coding: utf-8 -*-
"""E.V. 主流程：听懂 -> 执行 -> 回答 -> 记录；支持连续对话纠正（撤销+重做）"""
import json, pathlib, time, datetime, warnings
warnings.filterwarnings("ignore")
from understand import Understander, call_llm, ENV, HOME_CTX
from executor import execute
from capabilities import CAPS, device_of, action_list_for_teacher
import urllib.request

BASE = pathlib.Path(__file__).parent.parent
LOG  = BASE / "traces.jsonl"

class EV:
    def __init__(self, dry_run=True, thresh=0.35, learn=True):
        self.u=Understander(thresh); self.dry=dry_run; self.learn=learn
        self.last=None          # 上一轮：{text, action, device, ...}
        self.pending=None       # 待确认的高危动作
    def _log(self, rec):
        with LOG.open("a",encoding="utf-8") as f: f.write(json.dumps(rec,ensure_ascii=False)+"\n")

    def _undo(self, action):
        """撤销一个已执行的动作"""
        cap=CAPS.get(action) or {}
        if cap.get("kind")=="scene":
            undone=[]
            for st in cap.get("steps",[]):
                rev=CAPS.get(st,{}).get("undo")
                if rev: execute(rev, dry_run=self.dry); undone.append(device_of(st) or st)
            return undone
        rev=cap.get("undo")
        if rev:
            execute(rev, dry_run=self.dry)
            return [device_of(action) or action]
        return []

    CONFIRM_YES=("确认","确定","是的","对","好","执行","可以","嗯")
    CONFIRM_NO=("取消","算了","不用","不要","别")

    def handle(self, text):
        t0=time.time()
        # —— 待确认的高危动作 ——
        if self.pending:
            act=self.pending; self.pending=None
            if any(k in text for k in self.CONFIRM_NO):
                rec=dict(ts=datetime.datetime.now().isoformat(timespec="seconds"),text=text,
                         event="confirm_declined",action=act,layer="确认",
                         total_ms=round((time.time()-t0)*1000),ok=True,reply="好，不开了")
                self._log(rec); return rec
            if any(k in text for k in self.CONFIRM_YES):
                r=execute(act, dry_run=self.dry, confirmed=True)
                rec=dict(ts=datetime.datetime.now().isoformat(timespec="seconds"),text=text,
                         event="confirmed",action=act,device=r.get("device"),layer="确认",
                         total_ms=round((time.time()-t0)*1000),ok=r["ok"],reply=r["reply"])
                self._log(rec); self.last=dict(text=text,action=act,device=r.get("device"))
                return rec
            # 既不是确认也不是取消，当新指令处理（下面继续）
        # —— 交给理解层判断：纠正 还是 新指令（本地先认，拿不准问大模型）——
        u=self.u.understand(text, learn=self.learn, last=self.last)
        if u.get("is_correction"):
            right=u.get("action"); undone=[]
            if u.get("undo") and self.last and self.last.get("action"):
                undone=self._undo(self.last["action"])
            if right:
                r=execute(right, dry_run=self.dry)
                # 学习：把用户原来那句话重新标注成正确动作
                self.learn_correction((self.last or {}).get("text",text), right)
                parts=[]
                if undone: parts.append(f"已撤销{ '、'.join(undone) }")
                parts.append(r["reply"])
                reply="，".join(parts)
                rec=dict(ts=datetime.datetime.now().isoformat(timespec="seconds"), text=text,
                         event="correction", corrected_from=(self.last or {}).get("action"), action=right,
                         device=r.get("device"), undone=undone, layer=u["layer"],
                         total_ms=round((time.time()-t0)*1000), ok=r["ok"], reply=reply)
                self._log(rec)
                self.last=dict(text=(self.last or {}).get("text",text), action=right, device=r.get("device"))
                return rec
            # 只撤销、不重做
            reply=("已撤销"+"、".join(undone)) if undone else "好的，不做了"
            rec=dict(ts=datetime.datetime.now().isoformat(timespec="seconds"), text=text,
                     event="undo", action=None, undone=undone, layer=u["layer"],
                     total_ms=round((time.time()-t0)*1000), ok=True, reply=reply)
            self._log(rec); self.last=None
            return rec

        # —— 正常一轮（u 上面已算）——
        acts=u.get("actions") or ([u["action"]] if u.get("action") else [])
        if not acts:
            r={"ok":False,"reply":"这个我还不会，要不换个说法？","detail":None}
        elif len(acts)==1:
            r=execute(acts[0], dry_run=self.dry)
        else:
            # 一句话多个意图：依次执行，回答合并
            rs=[execute(a, dry_run=self.dry) for a in acts]
            r={"ok":all(x["ok"] for x in rs),
               "reply":"，".join(x["reply"] for x in rs),
               "device":"、".join(str(x.get("device") or "") for x in rs if x.get("device")),
               "detail":[x.get("detail") for x in rs],
               "need_confirm":any(x.get("need_confirm") for x in rs)}
        if r.get("need_confirm"): self.pending=u["action"]
        rec=dict(ts=datetime.datetime.now().isoformat(timespec="seconds"), text=text,
                 action=u["action"], actions=acts, layer=u["layer"], conf=round(u.get("conf") or 0,3),
                 device=r.get("device"), entity=r.get("entity"),
                 understand_ms=round(u["ms"]), total_ms=round((time.time()-t0)*1000),
                 ok=r["ok"], reply=r["reply"])
        self._log(rec)
        self.last=dict(text=text, action=u["action"], device=r.get("device"))
        rec["detail"]=r.get("detail")
        return rec

    def learn_correction(self, text, right_action):
        self.u.store["examples"]=[e for e in self.u.store["examples"] if e["text"]!=text]
        self.u.store["examples"].append({"text":text,"action":right_action})
        for k,v in list(self.u.store["l1"].items()):
            if k==text and v!=right_action: self.u.store["l1"][k]=right_action
        self.u.save(); self.u.retrain()
        try:
            import regression; regression.add_case(text, right_action, src="correction")
        except Exception: pass

    def correct(self, text, right_action):
        self.learn_correction(text, right_action)
        return f"记住了，「{text}」是 {CAPS[right_action]['name']}"

if __name__=="__main__":
    import sys
    dry = "--real" not in sys.argv
    ev=EV(dry_run=dry)
    print("E.V. 已启动。" + ("（dry-run，不会真动设备）" if dry else "（真实控制模式）"))
    print("直接说话即可；说错了就自然地纠正（如「不对，我说的是主卧」）；`:退出`\n")
    while True:
        try: t=input("你> ").strip()
        except (EOFError,KeyboardInterrupt): break
        if not t: continue
        if t in (":退出",":q"): break
        r=ev.handle(t)
        dev=f" → {r['device']}" if r.get("device") else ""
        meta=f"[{r.get('layer')} {r['total_ms']}ms" + (f" conf={r['conf']}" if r.get('conf') is not None else "") + "]"
        print(f"E.V.> {r['reply']}{dev}   {meta}")
