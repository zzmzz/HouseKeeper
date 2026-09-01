# -*- coding: utf-8 -*-
"""重训微调小模型（daily loop 的蒸馏阶段调用）

流程：导出训练数据 -> 传到 Mac mini -> LoRA 微调 -> 在考卷上评测
   -> **过了晋升门槛才换上去**，否则保留旧 adapter。

和现在重训 n-gram 是同一套逻辑，只是把学生换成了 0.6B。
"""
import json, pathlib, subprocess, sys, time, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import regression
from understand import STORE

BASE = pathlib.Path(__file__).parent.parent
HOST = "z@192.168.8.188"
REMOTE = "/tmp/evbench"
MODEL = "mlx-community/Qwen3-0.6B-4bit"
SYS = "把用户的话映射到家庭助手的动作 id。只输出 JSON：{\"actions\":[\"<id>\"]}"

def _ssh(cmd, timeout=1800):
    return subprocess.run(["ssh", HOST, f"export PATH=$PATH:/Users/z/Library/Python/3.9/bin; "
                           f"cd {REMOTE} && {cmd}"], capture_output=True, text=True, timeout=timeout)

def export_data(run=None):
    """导出训练/验证/考卷，考卷严格排除在训练外"""
    import random; random.seed(7)
    store = json.loads(STORE.read_text("utf-8"))
    gate = {i["text"] for i in regression.load("gate")}
    seen, rows = set(), []
    def add(t, a):
        if t in gate or t in seen: return
        seen.add(t)
        rows.append({"messages":[{"role":"system","content":SYS},
                                 {"role":"user","content":t},
                                 {"role":"assistant","content":json.dumps({"actions":[a]},ensure_ascii=False)}]})
    for e in store["examples"]: add(e["text"], e["action"])
    for t,a in store["l1"].items(): add(t,a)
    random.shuffle(rows)
    nv = max(20, len(rows)//12)
    out = BASE/"finetune"; out.mkdir(exist_ok=True)
    (out/"train.jsonl").write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in rows[nv:]),"utf-8")
    (out/"valid.jsonl").write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in rows[:nv]),"utf-8")
    test=[{"messages":[{"role":"system","content":SYS},{"role":"user","content":i["text"]},
           {"role":"assistant","content":json.dumps({"actions":[i["action"]]},ensure_ascii=False)}]}
          for i in regression.load("gate")]
    (out/"test.jsonl").write_text("\n".join(json.dumps(r,ensure_ascii=False) for r in test),"utf-8")
    return len(rows)-nv, nv, len(test)

def run_all(run=None):
    def note(m):
        print(f"    {m}", flush=True)
        if run: run.note(m)
    tr,va,te = export_data()
    note(f"训练 {tr} / 验证 {va} / 考卷 {te}（考卷不参与训练）")

    # 同步到 Mac mini
    subprocess.run(f"cd {BASE} && tar czf - finetune | ssh {HOST} 'cd {REMOTE} && tar xzf -'",
                   shell=True, timeout=120, capture_output=True)

    # 先测旧 adapter 在新考卷上的成绩（晋升基准）
    old = _ssh("env -u HF_ENDPOINT python3 bench_ft.py --model %s --adapter adapters-0.6b --n 169 "
               "2>/dev/null | grep 准确率" % MODEL, timeout=900)
    before = old.stdout.strip() or "（无旧模型）"
    note(f"旧模型：{before}")

    # 训练到候选目录
    t0=time.time()
    r = _ssh(f"env -u HF_ENDPOINT python3 -m mlx_lm lora --model {MODEL} --train --data finetune "
             f"--iters 600 --batch-size 8 --num-layers 8 --learning-rate 1e-4 "
             f"--adapter-path adapters-cand --steps-per-report 200 --steps-per-eval 300 2>&1 | tail -3",
             timeout=2400)
    note(f"训练完成 {time.time()-t0:.0f}s")

    new = _ssh("env -u HF_ENDPOINT python3 bench_ft.py --model %s --adapter adapters-cand --n 169 "
               "2>/dev/null | grep 准确率" % MODEL, timeout=900)
    after = new.stdout.strip()
    note(f"新模型：{after}")

    def pct(s):
        try: return float(s.split("=")[1].strip().rstrip("%"))
        except Exception: return -1
    b, a = pct(before), pct(after)
    if a >= b:
        _ssh("rm -rf adapters-0.6b.bak && mv adapters-0.6b adapters-0.6b.bak 2>/dev/null; "
             "mv adapters-cand adapters-0.6b")
        note(f"✅ 晋升（{b:.0f}% -> {a:.0f}%），旧 adapter 已备份")
        note("   重启 Mac mini 上的 mlx_server 生效")
        return {"promoted":True,"before":b,"after":a}
    _ssh("rm -rf adapters-cand")
    note(f"❌ 回滚：新模型 {a:.0f}% 不如旧的 {b:.0f}%，不换")
    return {"promoted":False,"before":b,"after":a}

if __name__=="__main__":
    print("重训微调小模型"); print(json.dumps(run_all(), ensure_ascii=False))
