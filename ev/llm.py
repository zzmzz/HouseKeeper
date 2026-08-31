# -*- coding: utf-8 -*-
"""模型层：两个后端，按"在不在用户等待路径上"分工。

  fast(...)   -> DeepSeek（公司endpoint，~1-2s）  运行时兜底，用户在等
  smart(...)  -> Claude 无头（~13s，走 OAuth）    离线高阶任务，没人等

分工原则：延迟敏感 & 高频 -> fast；质量敏感 & 低频 -> smart。
"""
import json, pathlib, subprocess, urllib.request

BASE = pathlib.Path(__file__).parent.parent
def _env():
    d={}
    for line in (BASE/".env").read_text("utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k,v=line.split("=",1); d[k.strip()]=v.strip()
    return d
ENV=_env()

def fast(system, user, max_tokens=200, temperature=0.0, timeout=40):
    """DeepSeek：运行时兜底。用户正在等，必须快。"""
    body=json.dumps({"model":ENV["EV_MODEL"],
        "messages":[{"role":"system","content":system},{"role":"user","content":user}],
        "max_tokens":max_tokens,"temperature":temperature}).encode()
    req=urllib.request.Request(ENV["EV_API_URL"]+"/v1/chat/completions",data=body,
        headers={"Authorization":"Bearer "+ENV["EV_API_KEY"],"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"].strip()

def smart(prompt, timeout=300):
    """Claude 无头：离线高阶任务。慢但强，没人在等。"""
    r = subprocess.run(["claude","-p"], input=prompt, capture_output=True,
                       text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"claude failed: {r.stderr[:200]}")
    return r.stdout.strip()

def parse_json(text):
    """两个后端都可能裹 ```json 或加解释，统一剥壳"""
    t=text.strip()
    if "```" in t:
        seg=t.split("```")
        for i in range(1,len(seg),2):
            body=seg[i]
            if body.startswith("json"): body=body[4:]
            t=body.strip(); break
    i,j = min([x for x in (t.find("{"),t.find("[")) if x>=0], default=0), max(t.rfind("}"),t.rfind("]"))
    if j>i: t=t[i:j+1]
    return json.loads(t)

# 路由表（写死在这里，别散落各处）
ROUTING = {
  # 运行时（用户在等）-> fast
  "intent_fallback":      "fast",    # L3 意图兜底
  "correction_resolve":   "fast",    # 纠正解析（也在对话中）
  # 离线（没人等，要质量）-> smart
  "generate_training":    "smart",   # 造训练数据
  "generate_regression":  "smart",   # 造回归测试题
  "audit_labels":         "smart",   # 质检已学标注（抓毒数据）
  "audit_registry":       "smart",   # 体检能力注册表（查漏设备）
  "distill_review":       "smart",   # 蒸馏晋升前的复核
}
