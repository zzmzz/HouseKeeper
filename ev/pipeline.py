# -*- coding: utf-8 -*-
"""E.V. Loop 流水线：阶段编排 + 进度事件 + 报告。

两个入口：
  bootstrap.py  冷启动 0→成熟：只给一份能力清单，自动跑到可用状态
  daily.py      日常 1→n：从真实交互记录持续自我改进

所有阶段把进度写成 JSONL 事件（run_log/），网页可以直接渲染成演示。
"""
import json, pathlib, time, datetime

BASE = pathlib.Path(__file__).parent.parent
RUNS = BASE / "runs"; RUNS.mkdir(exist_ok=True)

class Run:
    def __init__(self, kind):
        self.kind = kind
        self.id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = RUNS / f"{kind}-{self.id}.jsonl"
        self.t0 = time.time()
        self.stages = []
        self._emit("run_start", kind=kind, id=self.id)

    def _emit(self, ev, **kw):
        rec = dict(ev=ev, t=round(time.time()-self.t0, 2), **kw)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def stage(self, name, desc=""):
        return Stage(self, name, desc)

    def note(self, msg, **kw):
        print(f"    {msg}", flush=True)
        self._emit("note", msg=msg, **kw)

    def metric(self, key, value, unit="", note=""):
        print(f"    · {key}: {value}{unit}" + (f"  （{note}）" if note else ""), flush=True)
        self._emit("metric", key=key, value=value, unit=unit, note=note)

    def finish(self, **summary):
        self._emit("run_end", elapsed=round(time.time()-self.t0,1), **summary)
        print(f"\n完成，用时 {time.time()-self.t0:.0f}s")
        print(f"记录：{self.path}")
        return self.path

class Stage:
    def __init__(self, run, name, desc):
        self.run, self.name, self.desc = run, name, desc
    def __enter__(self):
        self.t = time.time()
        n = len(self.run.stages)+1
        print(f"\n[{n}] {self.name}" + (f" — {self.desc}" if self.desc else ""), flush=True)
        self.run._emit("stage_start", name=self.name, desc=self.desc, n=n)
        self.run.stages.append(self.name)
        return self.run
    def __exit__(self, et, ev, tb):
        ok = et is None
        el = round(time.time()-self.t, 1)
        self.run._emit("stage_end", name=self.name, ok=ok, elapsed=el,
                       error=(str(ev)[:200] if ev else None))
        print(f"    ({el}s)" + ("" if ok else f"  ✗ {ev}"), flush=True)
        return False
