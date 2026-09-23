# -*- coding: utf-8 -*-
"""E.V. HTTP 服务：给各种语音端调用。

    POST /ask   {"text": "开下浴霸", "session": "xiaoai"}
             -> {"reply": "浴霸开了", "action": "bath_heater_on",
                 "device": "浴霸", "layer": "L2", "ms": 3,
                 "need_confirm": false, "handled": true}

    GET  /health -> {"ok": true, "capabilities": 65, "model": "mlx" 或 "cloud"}

handled=false 表示 E.V. 管不了这句话（不是家居指令），
语音端应该把它交回原来的助手处理。

用法：
    python3 ev_server.py                # dry-run，不会真动设备
    python3 ev_server.py --real         # 真实控制
    python3 ev_server.py --port 8848
"""
import json, os, sys, time, pathlib, warnings, threading
warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path(__file__).parent / "ev"))
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent import EV
from capabilities import CAPS

DRY = "--real" not in sys.argv
PORT = int(sys.argv[sys.argv.index("--port")+1]) if "--port" in sys.argv else 8848
# 两套环境都学习，但**写各自的数据文件**（EV_ENV 决定，见 understand._envfile）。
# 早先的做法是"测试环境干脆不学"，但那等于把演示和试用这最真实的语料扔掉。
# 现在改成隔离 + 回流：测试环境自己学自己的，好东西用 publish.py 复核后合并
# 进真实环境。隔离解决的是并发写整份覆盖的问题，不是"测试数据没价值"。
LEARN = "--no-learn" not in sys.argv

_sessions = {}      # session -> EV（每个语音端一份上下文，纠正/确认互不干扰）
_lock = threading.Lock()

# 哪些 session 是真的语音入口。只有这些的输入才算"用户真实说过的话"，
# 其余（演示页、curl 测试）一律标成测试——它们不该进训练。
VOICE_SESSIONS = set((os.environ.get("EV_VOICE_SESSIONS") or "xiaoai").split(","))


def get_ev(session, room=None):
    """每个语音端一个 EV 实例。room = 这个端在哪个房间，
    决定「打开空调」这类没点名房间的指令落在哪台设备上。"""
    with _lock:
        ev = _sessions.get(session)
        if ev is None:
            origin = "voice" if session in VOICE_SESSIONS else "test"
            ev = EV(dry_run=DRY, learn=LEARN, session=session, origin=origin)
            _sessions[session] = ev
        if room and ev.u.room != room:
            ev.u.room = room
        return ev

# ---- daily loop 手动触发 ----
import subprocess, re as _re
_daily = {"proc": None, "log": pathlib.Path("/tmp/ev_daily_web.log"), "started": None}

def _daily_start():
    p = _daily["proc"]
    if p and p.poll() is None:
        return {"ok": False, "running": True, "msg": "已经在跑了"}
    _daily["log"].write_text("", "utf-8")
    _daily["proc"] = subprocess.Popen(
        [sys.executable, "daily.py"],
        cwd=str(pathlib.Path(__file__).parent / "ev"),
        stdout=_daily["log"].open("w"), stderr=subprocess.STDOUT)
    _daily["started"] = time.time()
    return {"ok": True, "running": True, "pid": _daily["proc"].pid}

def _did_of(r):
    """从执行结果里抽出"实际做了哪些动作"。三种来源要统一：
       L1/L2 单动作 -> action；多意图 -> actions；L3 走 agent -> detail.did"""
    out = []
    from capabilities import CAPS as _C
    for a in (r.get("actions") or ([r["action"]] if r.get("action") else [])):
        # 场景是一条能力、但实际动了好几台设备。只记一条的话，
        # 「我要睡了」关掉 12 样东西会显示成「执行 1 步」，画面自相矛盾。
        steps = (_C.get(a) or {}).get("steps") or []
        if steps:
            for st in steps:
                out.append({"action": st, "via": "场景 %s" % a})
        else:
            out.append({"action": a, "via": "capability"})
    d = r.get("detail")
    if isinstance(d, dict):
        for x in (d.get("did") or []):
            if x.get("kind") == "capability":
                out.append({"action": x.get("action"), "via": "L3→能力"})
            else:
                out.append({"action": "%s → %s" % (x.get("service"), x.get("entity")),
                            "via": "L3→直调"})
    return out


# ---- 演示用：把闭环后半程也做成接口 ----
# 前三步（问话/质检/分类）产出的是"待办"，但那只是 loop 的前半。
# 后半是：提 issue -> 实现出 PR -> 合并同步 -> 补 L1/训练样例 -> 重训过门槛 -> 上线。
# 不把这半程也接进来，演示就停在"发现了问题"，看不出这套东西怎么自己长出能力。

def _demo_push_issues(gaps_payload, push=None):
    """把这次分析出的缺口提成 GitHub issue。

    只提**这次分析出来的**，不动 gaps.json 里的历史积压——
    演示时要的是"我刚说的这句话，变成了一条 issue"这个因果，
    混进历史条目就看不清了。
    """
    import gaps as G
    sys.path.insert(0, str(pathlib.Path(__file__).parent / "loop"))
    import gh as GH
    GH.ensure_labels()
    out = []
    for g in (gaps_payload or []):
        gid = g.get("id") or ("gap-" + __import__("hashlib").md5(
            (g.get("title") or "").encode()).hexdigest()[:10])
        item = dict(g); item["id"] = gid
        item.setdefault("hits", len(g.get("samples") or []) or 1)
        item.setdefault("first_seen", G._today()); item.setdefault("last_seen", G._today())
        old = GH.find_issue_by_gap(gid)
        if old:
            out.append({"title": g.get("title"), "issue": old["number"], "new": False,
                        "url": "https://github.com/%s/issues/%s" % (GH.REPO, old["number"])})
            continue
        if push: push("stage", "提 issue：%s" % (g.get("title") or "")[:40])
        num = GH.create_gap_issue(item)
        out.append({"title": g.get("title"), "issue": num, "new": True,
                    "url": "https://github.com/%s/issues/%s" % (GH.REPO, num)})
    return {"issues": out, "repo": GH.REPO}


def _gap_session(gid):
    """从待办直接开会话。

    **先把 issue 落下来再开会话**，哪怕你只是想聊两句：
    会话是临时的（tmux 关了就没了），issue 才是那个能留下评论、
    能被 PR 引用、能在下一轮被认出"这条已经在做了"的锚点。
    没有它，聊出来的结论就只活在那个终端里。
    已经提过 issue 的复用旧的，不重复提。
    """
    import gaps as G
    sys.path.insert(0, str(pathlib.Path(__file__).parent / "loop"))
    import gh as GH
    all_gaps = G.load() if hasattr(G, "load") else []
    g = next((x for x in all_gaps if x.get("id") == gid), None)
    if not g:
        return {"error": "没有这条待办：%s" % gid}
    num = g.get("issue")
    created = False
    if not num:
        old = GH.find_issue_by_gap(gid)
        if old:
            num = old["number"]
        else:
            GH.ensure_labels()
            num = GH.create_gap_issue(g)
            created = True
        try:
            G.set_issue(gid, num)          # 记回 gaps.json，下次直接复用
        except Exception:
            pass
    r = _demo_session(num)
    if "error" in r:
        return r
    r.update({"issue": num, "issue_new": created,
              "issue_url": "https://github.com/%s/issues/%s" % (GH.REPO, num),
              "title": g.get("title")})
    return r


def _demo_implement(push=None):
    """跑一轮实现：打了 approved 标签的 issue -> 代码 -> PR。"""
    return _run_script(["python3", "-u", "loop/implement.py"], push, timeout=2400,
                       done_pat="PR ")


def _gh_env():
    """gh 用独立的 PR token（全局那个 fine-grained PAT 提不了 PR）。"""
    env = dict(os.environ)
    if "GH_TOKEN" not in env:
        tok = pathlib.Path.home() / ".config/gh-pr-token"
        if tok.exists():
            env["GH_TOKEN"] = tok.read_text().strip()
    env.pop("GITHUB_TOKEN", None)
    return env


def _home_repo():
    return os.environ.get("EV_HOME_REPO", "zzmzz/HouseKeeper-home")


def _gh_mod():
    """复用 loop/gh.py：它有重试白名单（EOF / TLS handshake / 502…）和 token 处理。
    这台机器访问 GitHub 会抖，自己再写一份没重试的调用迟早踩到。"""
    import importlib.util, sys as _s
    if "ev_loop_gh" in _s.modules:
        return _s.modules["ev_loop_gh"]
    f = pathlib.Path(__file__).parent / "loop" / "gh.py"
    spec = importlib.util.spec_from_file_location("ev_loop_gh", f)
    m = importlib.util.module_from_spec(spec)
    _s.modules["ev_loop_gh"] = m
    spec.loader.exec_module(m)
    return m


def _demo_prs():
    """还没合并的 PR。页面要能直接看见——PR 挂着不合并，后面全是白做。"""
    try:
        G = _gh_mod()
        prs = G.gh_json("pr", "list", "--repo", G.REPO, "--state", "open",
                        "--json", "number,title,headRefName,mergeable") or []
        return {"prs": prs}
    except Exception as e:
        return {"error": str(e)[:200], "prs": []}


def _demo_merge(nums, push=None):
    """合并 PR -> 同步进运行环境 -> 重启生效。三件事必须连在一起。

    分成三个按钮的时候实测就是漏了合并那步：sync 从 main clone，改动还在
    分支上，于是报「没有要同步的」——然后照样点了重训，白跑 17 分钟。
    缺任何一件，前面的活都白做：PR 不合并 sync 拉不到；sync 了不重启，
    CAPS 和 store 还是进程启动时读的那份。
    """
    import subprocess
    log = []
    def out(line=""):
        log.append(line)
        if push: push("text", line[:200])

    nums = [str(n) for n in (nums or []) if str(n).strip()]
    if not nums:
        return {"ok": False, "log": ["没选要合并的 PR"]}

    G = _gh_mod()
    for n in nums:
        try:
            G.gh("pr", "merge", n, "--squash", "--repo", G.REPO, timeout=180)
            out("✓ 已合并 #%s" % n)
        except Exception as e:
            # 合并可能实际成功了、只是响应丢了（EOF 重试后会报 not mergeable）。
            # 失败后回查一次真实状态，别把已经合了的报成失败。
            st = ""
            try:
                st = (G.gh_json("pr", "view", n, "--repo", G.REPO,
                                "--json", "state", check=False) or {}).get("state", "")
            except Exception:
                pass
            if st == "MERGED":
                out("✓ 已合并 #%s（首次响应丢了，回查确认）" % n)
            else:
                out("✗ 合并 #%s 失败：%s" % (n, str(e)[:200]))
                return {"ok": False, "log": log}

    out(); out("── 同步进运行环境 ──")
    r = _run_script(["python3", "-u", "loop/sync_home.py", "--apply"], push, timeout=1800)
    log += r.get("log") or []
    if not r.get("ok"):
        return {"ok": False, "log": log, "code": r.get("code")}

    out(); out("── 重启服务（CAPS 和 store 都是进程启动时读一次）──")
    # 必须脱离本进程：pm2 restart 会杀掉正在回这条 HTTP 的自己，
    # 响应就发不出去了。延迟 3 秒，等这次响应写完。
    try:
        subprocess.Popen(["setsid", "sh", "-c", "sleep 3; pm2 restart ev-demo"],
                         start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        out("3 秒后重启，页面会自己等它回来。")
    except Exception as e:
        out("⚠️ 自动重启没起来（%s），手动跑：pm2 restart ev-demo" % str(e)[:80])
    return {"ok": True, "log": log, "restarting": True}


def _demo_sync(push=None):
    """合并后的同步：拉回运行环境 + 给新能力补 L1/训练样例/考题。"""
    return _run_script(["python3", "-u", "loop/sync_home.py", "--apply"], push, timeout=1800)


def _demo_session(issue):
    """给一个 issue 起交互式实现会话，返回网页里嵌终端用的地址。"""
    if not issue:
        return {"error": "要给 issue 号"}
    import subprocess
    env = dict(os.environ, EV_TTYD_HOST=os.environ.get(
        "EV_TTYD_HOST", "http://%s:7681" % (os.environ.get("EV_HOST_IP") or "192.168.1.202")))
    if "GH_TOKEN" not in env:
        tok = pathlib.Path.home() / ".config/gh-pr-token"
        if tok.exists():
            env["GH_TOKEN"] = tok.read_text().strip()
    r = subprocess.run(["python3", "loop/session.py", "start", str(issue)],
                       cwd=str(pathlib.Path(__file__).parent), env=env,
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        return {"error": (r.stderr or r.stdout or "")[-400:]}
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"error": "会话起了但返回不是 JSON：%s" % r.stdout[-200:]}


def _demo_sessions():
    import subprocess
    r = subprocess.run(["python3", "loop/session.py", "list"],
                       cwd=str(pathlib.Path(__file__).parent),
                       capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout or "[]")
    except Exception:
        return []


def _demo_pr(issue, push=None):
    """会话聊完了，按两个仓分别出 PR。"""
    if not issue:
        return {"ok": False, "log": ["要给 issue 号"]}
    return _run_script(["python3", "loop/pr.py", str(issue)], push, timeout=600)


def _demo_retrain(push=None):
    """重训 + 双卷门槛。这一步最慢（约 17 分钟），但它才是"学会了"的证明。"""
    return _run_script(["python3", "-u", "ev/retrain_lora.py"], push, timeout=3000)


def _run_script(cmd, push=None, timeout=1800, done_pat=None):
    """跑一个脚本，逐行回传进度。**不吞非零退出码**——
    脚本失败必须让前端看见，而不是显示成"完成了但什么也没发生"。"""
    import subprocess, time as _t
    env = dict(os.environ, EV_ENV="")
    pr = subprocess.Popen(cmd, cwd=str(pathlib.Path(__file__).parent),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, bufsize=1, env=env)
    lines, t0 = [], _t.time()
    for line in pr.stdout:
        if _t.time() - t0 > timeout:
            pr.kill(); lines.append("（超时 %ds，已中止）" % timeout); break
        line = line.rstrip()
        if not line: continue
        lines.append(line)
        if push: push("text", line[:200])
    rc = pr.wait(timeout=60)
    return {"ok": rc == 0, "code": rc, "log": lines[-60:]}


def _daily_status():
    p = _daily["proc"]
    running = bool(p and p.poll() is None)
    txt = _daily["log"].read_text("utf-8", errors="ignore") if _daily["log"].exists() else ""
    # 抽出阶段和指标行
    lines = [l.rstrip() for l in txt.splitlines() if l.strip()]
    return {"running": running, "started": _daily["started"],
            "elapsed": round(time.time() - _daily["started"]) if _daily["started"] else 0,
            "exit": (p.poll() if p else None), "lines": lines[-40:]}


# ---- 演示用：把大模型那两步做成后台任务 ----
# 分类/质检一次要 10-60 秒。同步返回浏览器会超时，页面也只能干等；
# 拆成「起任务 -> 轮询」后，前端能一直显示已耗时，录屏时看得见它在干活。
_jobs = {}
_jobn = [0]

def _job_start(fn):
    with _lock:
        _jobn[0] += 1
        jid = "j%d" % _jobn[0]
        _jobs[jid] = {"state": "running", "t0": time.time(), "result": None,
                      "error": None, "log": []}
    def push(kind, text):
        """把一步进度塞进任务日志。整轮要几分钟，不实时吐出来页面就是干等——
        而这些中间步骤（它在查什么、查到了什么）恰恰是最值得演示的部分。"""
        j = _jobs.get(jid)
        if j is None:
            return
        with _lock:                     # 和 _job_get 的快照互斥，见下面那段注释
            j["log"].append({"kind": kind, "text": text, "t": round(time.time() - j["t0"], 1)})
            del j["log"][:-200]         # 只留最近 200 条，别让长任务把内存吃光

    def run():
        try:
            r = fn(push) if _takes_progress(fn) else fn()
            _jobs[jid].update(state="done", result=r)
        except Exception as e:
            import traceback; traceback.print_exc()
            _jobs[jid].update(state="error", error=str(e))
    threading.Thread(target=run, daemon=True).start()
    return jid

def _takes_progress(fn):
    import inspect
    try: return len(inspect.signature(fn).parameters) >= 1
    except Exception: return False


def _job_get(jid, since=0):
    j = _jobs.get(jid)
    if not j: return {"state": "missing"}
    # 必须在锁里拷一份再返回。不然工作线程正往 log 里 append、还会
    # del log[:-200] 截断，而主线程同时在 json.dumps 遍历同一个列表——
    # 序列化到一半列表变了，吐出来的 JSON 就是坏的，前端报
    # "Invalid control character" 然后轮询直接挂掉，表现为页面永远卡在"分析中"。
    # 任务其实早跑完了。
    with _lock:
        log = list(j["log"][since:])
        n = len(j["log"])
    return {"state": j["state"], "elapsed": round(time.time() - j["t0"], 1),
            "result": j["result"], "error": j["error"],
            "log": log, "log_n": n}


# ---- 待办（能力缺口）----
def _gaps_load():
    import gaps as G, importlib
    importlib.reload(G)
    return G

def _gaps_list():
    G = _gaps_load()
    gs = G.load()
    order = {"open": 0, "dismissed": 1, "done": 2}
    gs = sorted(gs, key=lambda g: (order.get(g.get("status"), 9), -(g.get("hits") or 0)))
    return {"gaps": gs, "min_hits": getattr(G, "MIN_HITS", 2),
            "kind_cn": getattr(G, "KIND_CN", {})}

def _gaps_set(gid, status):
    """人工改状态。自动闭环靠可观测信号（新实体出现），但有些做完了系统看不见
    ——比如『去 CMA 机构做了次甲醛检测』，那就得能手动标一下。"""
    import json as _j, datetime
    G = _gaps_load()
    gs = G.load()
    hit = None
    for g in gs:
        if g.get("id") == gid:
            g["status"] = status
            if status == "done":
                g["done_at"] = datetime.date.today().isoformat()
                g["closed_by"] = "manual"      # 区分人工关闭和系统自动发现
            elif status == "open":
                g.pop("done_at", None); g.pop("closed_by", None)
                g["notified"] = None           # 重开就该重新提醒
            hit = g
            break
    if hit is None:
        return {"ok": False, "error": "没有 id=%s 的待办" % gid}
    G.save(gs)
    return {"ok": True, "gap": hit}


def _demo_runs(n=6):
    """读最近几次 daily loop 的真实运行轨迹。

    重训一次 4.5 分钟，现场演示等不起，所以这里给的是**历史真实记录**
    而不是当场跑。挑重点的是晋升门槛那一段——上次重训考卷从 91% 掉到
    90%，被门槛回滚了。这比一次成功的训练更能说明 loop 是有闸的。
    """
    import pathlib as _p
    out = []
    d = _p.Path(__file__).parent / "runs"
    for f in sorted(d.glob("daily-*.jsonl"), reverse=True)[:n]:
        stages, metrics, notes, end = [], [], [], {}
        for line in f.read_text("utf-8", errors="ignore").splitlines():
            try: r = json.loads(line)
            except Exception: continue
            e = r.get("ev")
            if e == "stage_start": stages.append({"name": r.get("name"), "desc": r.get("desc")})
            elif e == "metric":
                metrics.append({"stage": stages[-1]["name"] if stages else "",
                                "key": r.get("key"), "value": r.get("value"),
                                "unit": r.get("unit"), "note": r.get("note")})
            elif e == "note":
                notes.append({"stage": stages[-1]["name"] if stages else "", "msg": r.get("msg")})
            elif e == "run_end":
                end = {"promoted": r.get("promoted"), "before": r.get("before"),
                       "after": r.get("after"), "learned": r.get("learned"),
                       "elapsed": r.get("elapsed")}
        out.append({"id": f.stem, "stages": stages, "metrics": metrics,
                    "notes": notes, "end": end})
    return {"runs": out}


def _demo_audit(rows, push=None):
    from pipeline import Run
    import daily
    return {"bad": daily.audit_answers(Run("demo-audit"), rows=rows, on_progress=push)}

def _demo_classify(payload, push=None):
    """payload: {"missed":[...], "bad":[{"text","missing"}...]}

    两类分开传：「没接住的」和「答非所问的」要做的事不一样——
    前者是缺能力，后者是能力在但答得不对，分析时不该混成一堆。
    """
    from pipeline import Run
    import gaps
    if isinstance(payload, list):        # 兼容旧调用
        payload = {"missed": payload, "bad": []}
    # 这里**不吞异常**：任务标记成 error，前端显示"分类失败"。
    # 把失败显示成"0 条待办"比不显示更糟——那是在告诉用户一个假结论。
    found = gaps.classify(Run("demo-classify"),
                          payload.get("missed") or [],
                          bad_answers=payload.get("bad") or [],
                          on_progress=push)
    kept = set()
    for g in found:
        for t in (g.get("samples") or g.get("texts") or []): kept.add(t)
    allin = list(payload.get("missed") or []) + [
        (b.get("text") if isinstance(b, dict) else b) for b in (payload.get("bad") or [])]
    # 被丢弃的要报出来。只说"另有 N 条被判为不该我管"而不说是哪几条，
    # 人没法判断这个判断对不对——万一丢的是该做的呢。
    dropped = [t for t in allin if t not in kept]
    return {"dropped": dropped,
            "gaps": [{"kind": g.get("kind"), "title": g.get("title"),
                      "why": g.get("why"), "action": g.get("action"),
                      # 字段名是 samples——大模型按这个名字输出。
                      # 原来映射的是 texts，永远空，于是页面上没有原话，
                      # 卡片只剩一段抽象描述，人不知道它在说哪句指令。
                      "samples": g.get("samples") or g.get("texts") or []}
                     for g in found]}


class H(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path in ("/", "/console", "/index.html"):
            f = pathlib.Path(__file__).parent / "console.html"
            b = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers(); self.wfile.write(b); return
        if self.path.startswith("/pending"):
            import importlib, pending
            importlib.reload(pending)
            return self._send(pending.survey())
        if self.path in ("/todo", "/todo/"):
            f = pathlib.Path(__file__).parent / "todo.html"
            b = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers(); self.wfile.write(b); return
        if self.path.startswith("/gaps"):
            return self._send(_gaps_list())
        if self.path in ("/live", "/live/"):
            # 把日志文件实时推给页面。录屏要的是「真的在跑」，
            # 回放做不到这点——它只能证明「跑过」。
            f = pathlib.Path(os.environ.get("EV_LIVE_LOG", "/tmp/live-boot.log"))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            import time as _t
            # 断线要能接着放。闭环的第七步会重启本服务，连接必然断一次；
            # 原来断了就从头重推（页面会把整场重演一遍），或者页面自己关掉
            # 不再重连——实测后者，结果最后一步的验证压根没录进去。
            # 按 SSE 的规矩给每行发 id，浏览器重连时带 Last-Event-ID 回来，
            # 从那一行之后接着发。
            try:
                sent = int(self.headers.get("Last-Event-ID") or 0)
            except Exception:
                sent = 0
            idle = 0
            try:
                self.wfile.write(b"retry: 1000\n\n")
                self.wfile.flush()
                while idle < 3600:
                    if f.exists():
                        lines = f.read_text("utf-8", errors="ignore").splitlines()
                        if len(lines) > sent:
                            idle = 0
                            for line in lines[sent:]:
                                sent += 1
                                self.wfile.write(
                                    ("id: %d\ndata: %s\n\n" % (sent, line)).encode("utf-8"))
                            self.wfile.flush()
                            continue
                    idle += 1
                    _t.sleep(1)
            except Exception:
                pass
            return
        if self.path in ("/live2", "/live2/"):
            self.path = "/live"          # 复用同一套推送，只是读另一个日志
            os.environ["EV_LIVE_LOG"] = "/tmp/live-daily.log"
            return self.do_GET()
        if self.path in ("/daily2", "/daily2/"):
            f = pathlib.Path(__file__).parent / "live-daily.html"
            b = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers(); self.wfile.write(b); return
        if self.path in ("/boot", "/boot/"):
            f = pathlib.Path(__file__).parent / "live-boot.html"
            b = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers(); self.wfile.write(b); return
        if self.path.startswith("/replay"):
            # /replay/bootstrap · /replay/daily —— Loop 的时间轴回放（录屏用）
            path = self.path.split("?")[0].rstrip("/")     # 别把 ?speed=32 当成文件名
            kind = path.rsplit("/", 1)[-1] or "bootstrap"
            if kind == "replay": kind = "bootstrap"
            f = pathlib.Path(__file__).parent / ("replay-%s.html" % kind)
            if not f.exists():
                return self._send({"error": "还没生成 %s，先跑 make_replay.py" % f.name}, 404)
            b = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers(); self.wfile.write(b); return
        if self.path in ("/demo", "/demo/"):
            f = pathlib.Path(__file__).parent / "gap-demo.html"
            b = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers(); self.wfile.write(b); return
        if self.path.startswith("/demo/prs"):
            return self._send(_demo_prs())
        if self.path.startswith("/demo/runs"):
            return self._send(_demo_runs())
        if self.path.startswith("/demo/job"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            jid = (qs.get("id") or [""])[0]
            try: since = max(0, int((qs.get("since") or ["0"])[0] or 0))
            except Exception: since = 0     # since= 传空串时 int("") 会抛，别让它变成 500
            return self._send(_job_get(jid, since))
        if self.path.startswith("/daily/status"):
            return self._send(_daily_status())
        if self.path.startswith("/health"):
            ev = get_ev("_probe")
            import understand as _U
            return self._send({"ok": True, "capabilities": len(CAPS),
                               "l2": ("mlx:" + _U.MLX_URL) if _U.MLX_URL else "未配置（全走云端）",
                               "rooms": {k: v.u.room for k, v in _sessions.items() if v.u.room},
                               "dry_run": DRY, "learn": LEARN,
                               # L3 直调 HASS 的 dry 口径。单独列出来是因为它和
                               # executor 曾经用过两个来源，真实环境里 executor 真动设备
                               # 而 agent 空跑，回复「灯开了」但灯不亮。现在同源，
                               # 但值得能一眼核对。
                               "l3_dry": ev.u.dry,
                               "sessions": list(_sessions)})
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        if self.path.startswith("/daily"):
            return self._send(_daily_start())
        if self.path.startswith("/reset"):
            try:
                n = int(self.headers.get("Content-Length", 0))
                sess = (json.loads(self.rfile.read(n) or b"{}")).get("session", "default")
            except Exception:
                sess = "default"
            with _lock: _sessions.pop(sess, None)
            return self._send({"ok": True, "reset": sess})
        if self.path.startswith("/gaps/session"):
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                body = {}
            return self._send(_gap_session(body.get("id")))
        if self.path.startswith("/gaps/status"):
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception as e:
                return self._send({"error": "bad json: %s" % e}, 400)
            st = body.get("status")
            if st not in ("open", "done", "dismissed"):
                return self._send({"error": "status 只能是 open/done/dismissed"}, 400)
            return self._send(_gaps_set(body.get("id"), st))
        if self.path.startswith("/demo/step/"):
            # 闭环后半程：提 issue / 实现 / 同步 / 重训
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                body = {}
            what = self.path.rsplit("/", 1)[-1].split("?")[0]
            # 起会话是同步的：它只是 mkdir + clone + tmux，秒级完成，
            # 而且前端要立刻拿到 iframe 的地址。包成 job 反而要多轮询一次。
            if what == "session":
                return self._send(_demo_session(body.get("issue")))
            if what == "sessions":
                return self._send({"sessions": _demo_sessions()})
            fn = {"issues":  lambda push: _demo_push_issues(body.get("gaps"), push),
                  "merge":   lambda push: _demo_merge(body.get("prs"), push),
                  "implement": _demo_implement,
                  "sync":    _demo_sync,
                  "retrain": _demo_retrain,
                  "pr":      lambda push: _demo_pr(body.get("issue"), push)}.get(what)
            if not fn:
                return self._send({"error": "unknown step: %s" % what}, 400)
            return self._send({"job": _job_start(fn)})
        if self.path.startswith("/demo/audit") or self.path.startswith("/demo/classify"):
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception as e:
                return self._send({"error": "bad json: %s" % e}, 400)
            if self.path.startswith("/demo/audit"):
                rows = body.get("rows") or []
                return self._send({"job": _job_start(lambda push: _demo_audit(rows, push))})
            payload = {"missed": body.get("texts") or body.get("missed") or [],
                       "bad": body.get("bad") or []}
            return self._send({"job": _job_start(lambda push: _demo_classify(payload, push))})
        if not self.path.startswith("/ask"):
            return self._send({"error": "not found"}, 404)
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self._send({"error": f"bad json: {e}"}, 400)
        text = (body.get("text") or "").strip()
        if not text:
            return self._send({"error": "text is required"}, 400)
        try:
            r = get_ev(body.get("session","default"), body.get("room")).handle(text)
        except Exception as e:
            return self._send({"error": str(e), "handled": False}, 500)
        self._send({
            "reply": r.get("reply"), "action": r.get("action"),
            "actions": r.get("actions"), "device": r.get("device"),
            # 实际执行了哪些动作。**必须单独给一个字段**：
            #   多意图在 actions 数组里，而 L3(工具) 走 agent、没有 action，
            #   它做了什么原来只能从 device 字段里猜（那是给人看的设备名）。
            #   演示时看不到"到底执行了几步、对不对"，等于没法验收。
            "did": _did_of(r),
            "layer": r.get("layer"), "ms": r.get("total_ms"),
            # 「如实说了做不到」。这条跟 did 一样要单独给：它在日志里长得和
            # 成功一模一样（回答切题、没报错），调用方光看 reply 判不出来，
            # 而这恰恰是缺口队列最该收的一类。daily 那边靠 collect_unsupported 捞。
            "unsupported": bool(r.get("unsupported")),
            "need_confirm": bool(r.get("need_confirm")),
            "handled": bool(r.get("action")) or str(r.get("layer","")).startswith("L3"),   # false = 不是家居指令，交回原助手
            "room": get_ev(body.get("session","default")).u.room,
        })

    def log_message(self, *a): pass    # 静音默认访问日志

if __name__ == "__main__":
    print(f"E.V. HTTP 服务 :{PORT}"
          + ("（dry-run，不会真动设备）" if DRY else "（真实控制 ⚠）")
          + ("（学习开）" if LEARN else "（不学习）"))
    print(f"  能力 {len(CAPS)} 个 | POST /ask  GET /health")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
