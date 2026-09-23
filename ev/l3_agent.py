# -*- coding: utf-8 -*-
"""L3：能用工具的大模型。L1/L2 接不住的全归它。

原来这一层是「一次调用、从能力清单里挑一个 id」的分类器，比 L2 大但**答案空间一样**——
清单里没有的东西它也变不出来。次卧灯在 HASS 里躺着却没登记，三层一致地答错，
换更大的模型只是"更聪明地在同样的选项里挑"。所以整层换成了这个带工具的版本：
它能去 HASS 里搜、能调没登记过的实体、能跑 tools/ 里的脚本。

代价是慢：一次调用 1-3 秒变成多轮 5-15 秒。这个代价可以付，因为
L1/L2 接住了绝大多数流量，落到这儿的本来就是尾部。
纯闲聊（讲笑话/问股票）只需一轮 answer，2-3 秒就能回绝，不会真跑满 15 秒。

**它的产出不只是这一次的答复**：每次 call_service 都会记进 cap_proposals.jsonl，
daily loop 据此提"该把这个设备登记成能力"。用过一次就该被登记，
下次走 L1/L2 的正规路径，而不是每次都靠 L3 现找——否则它会变成一个
越用越慢、且绕过全部安全检查的后门。**这条回流是这层能力增长的方式。**
"""
import json, os, pathlib, time, urllib.request

import l3_tools as T

BASE = pathlib.Path(__file__).parent.parent
MAX_STEPS = int(os.environ.get("EV_L3_STEPS", os.environ.get("EV_L4_STEPS", "8")))


def _env():
    d = {}
    for line in (BASE / ".env").read_text("utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1); d[k.strip()] = v.strip()
    return d
ENV = _env()


import prompts as P

# 系统提示词放私有仓 prompts/l3_system.md——它是内容不是逻辑，会一直改。
# 实测：没在里面说清「commute_eta 自带解析谁在问」，模型绕了 13 轮 17 秒找"媳妇是谁"。
# 这类改动不该需要发版。
SYS = P.text("l3_system.md", """你是家庭语音助手 E.V. 的兜底层。前面两层（精确规则表、本地小模型）没接住这句话，所以轮到你。

你比它们多的东西：你能调工具，能直接查 HASS、能操作没登记过的设备、能跑用户提供的脚本。

工作方式：
1. 先判断这是不是家里的事。不是（问股票、讲笑话、查百科）就用 answer 说明这不归你管。
   但**日期时间、星期、农历这类用 sysinfo 就能拿到的，直接查了答，别推回去**——
   用户站在音箱前问「今天星期几」，回一句"这不归我管"是很蠢的。
2. 是家里的事，但你不确定有没有这个设备 —— **先 search_entities 搜一下**。
   前面几层答错，常常是因为设备真的在 HASS 里，只是没登记进能力清单。
3. 找到了：
   - 能力清单里有对应动作 -> 用 use_capability（它有完整的安全检查）
   - 清单里没有 -> 才用 call_service 直接操作
4. 查询类的问题，查到之后用 answer 把结果**用口语**说出来，不要念 entity_id。
   做不到的时候也一样：说「家里还没有睡觉这个场景」，别把 scene_sleep 这种内部代号念出来——这些话是从音箱里放出来给人听的。
5. 最后**必须**调一次 answer 收尾。

注意：
- 用户说的房间别称要认：次卧=客房=小卧室，主卧=我们房间=睡屋。
- 一句话里有多件事就分别做完再一起答复。
- 做不到的事直说做不到，并说清楚缺什么（比如"阳台没有土壤湿度传感器"），
  不要编一个看起来能用的答案。""")


def _post(messages, tools, timeout=60):
    body = json.dumps({"model": ENV["EV_MODEL"], "messages": messages,
                       "tools": tools, "temperature": 0, "max_tokens": 800}).encode()
    req = urllib.request.Request(ENV["EV_API_URL"] + "/v1/chat/completions", data=body,
                                 headers={"Authorization": "Bearer " + ENV["EV_API_KEY"],
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["choices"][0]["message"]


def run(text, room="", dry_run=True, execute_cap=None, caps_hint="", trace=None):
    """跑一轮 L4。

    execute_cap: 回调 (action_id) -> dict，用来执行能力清单里的动作。
                 由调用方注入，这样 L4 不必自己 import executor（避免循环依赖），
                 也保证走的是和 L1/L2/L3 完全相同的那条执行路径。
    """
    t0 = time.time()
    tools = T.schemas(caps_hint)
    msgs = [{"role": "system", "content": SYS},
            {"role": "user", "content": ("[我在%s] " % room if room else "") + text}]
    steps, reply, did = [], None, []
    unsupported = False

    for _ in range(MAX_STEPS):
        try:
            m = _post(msgs, tools)
        except Exception as e:
            return {"ok": False, "reply": "我这边连不上大模型", "error": str(e),
                    "steps": steps, "ms": (time.time() - t0) * 1000}
        calls = m.get("tool_calls") or []
        if not calls:
            reply = (m.get("content") or "").strip() or None
            break
        msgs.append({"role": "assistant", "content": m.get("content") or "",
                     "tool_calls": calls})
        for c in calls:
            fn = c["function"]["name"]
            try: args = json.loads(c["function"].get("arguments") or "{}")
            except Exception: args = {}
            out = _dispatch(fn, args, text, dry_run, execute_cap, did)
            steps.append({"tool": fn, "args": args, "out": out})
            if trace: trace(fn, args, out)
            msgs.append({"role": "tool", "tool_call_id": c["id"],
                         "content": json.dumps(out, ensure_ascii=False)[:2000]})
            if fn == "answer":
                reply = args.get("reply") or ""
                unsupported = bool(args.get("unsupported"))
        if reply is not None:
            break

    return {"ok": bool(reply), "reply": reply or "这个我还是没弄明白",
            "steps": steps, "did": did, "unsupported": unsupported,
            "ms": (time.time() - t0) * 1000}


def _dispatch(fn, args, text, dry_run, execute_cap, did):
    if fn == "search_entities":
        return T.t_search_entities(args.get("keyword"), int(args.get("limit") or 20))
    if fn == "get_state":
        return T.t_get_state(args.get("entity_id"))
    if fn == "entity_attrs":
        return T.t_entity_attrs(args.get("entity_id"))
    if fn == "list_domains":
        return T.t_list_domains()
    if fn == "render_template":
        return T.t_render(args.get("template"))
    if fn == "use_capability":
        aid = args.get("action_id")
        if not execute_cap:
            return {"error": "本次运行没接执行器"}
        r = execute_cap(aid, text)      # 原话要传下去，有些能力按"谁在问"给不同答案
        # 只有真做成了才记。被护栏拦下的（极性反了、场景对不上）不算，
        # **能力根本不存在**的也不算——execute 对没登记的 action_id 返回
        # ok=False/"这个我还不会"，但它不带 blocked，原来照样记一笔，于是
        # 「我要睡了」的日志写着"动了 scene_sleep"、回答里却说做不到，
        # 自相矛盾。did 只应该是实际发生过的事。
        if r.get("ok"):
            did.append({"kind": "capability", "action": aid})
        return r
    if fn == "call_service":
        r = T.t_call_service(args.get("service"), args.get("entity_id"),
                             args.get("data"), dry_run=dry_run, text=text)
        if r.get("ok"):
            did.append({"kind": "raw", "service": args.get("service"),
                        "entity": args.get("entity_id")})
        return r
    if fn == "sysinfo":
        return T.t_sysinfo(args.get("what"))
    if fn == "answer":
        return {"ok": True}
    if fn.startswith("script_"):
        return T.t_run_script(fn[len("script_"):], args, dry_run=dry_run)
    return {"error": "没有叫 %s 的工具" % fn}
