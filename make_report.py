# -*- coding: utf-8 -*-
"""把一次 run 的事件流渲染成可演示的网页。
用法：python3 make_report.py [runs/bootstrap-xxx.jsonl]  （不给则用最新一次）
"""
import json, pathlib, sys, glob, html

BASE = pathlib.Path(__file__).parent
def load(path=None):
    if not path:
        fs = sorted(glob.glob(str(BASE/"runs"/"*.jsonl")))
        if not fs: sys.exit("还没有 run 记录，先跑 bootstrap.py")
        path = fs[-1]
    evs = [json.loads(l) for l in pathlib.Path(path).read_text("utf-8").splitlines() if l.strip()]
    return path, evs

def build(path, evs):
    kind = next((e.get("kind") for e in evs if e["ev"]=="run_start"), "run")
    end  = next((e for e in evs if e["ev"]=="run_end"), {})
    stages, cur = [], None
    for e in evs:
        if e["ev"]=="stage_start":
            cur={"n":e["n"],"name":e["name"],"desc":e.get("desc",""),"items":[],"elapsed":None,"ok":True}
            stages.append(cur)
        elif e["ev"]=="stage_end" and cur:
            cur["elapsed"]=e.get("elapsed"); cur["ok"]=e.get("ok",True)
        elif e["ev"] in ("metric","note","curve") and cur:
            cur["items"].append(e)
    total = end.get("elapsed")
    title = "冷启动：0 → 成熟" if kind=="bootstrap" else "日常 Loop：持续自我改进"

    def esc(x): return html.escape(str(x))
    body=[]
    for s in stages:
        rows=[]
        for it in s["items"]:
            if it["ev"]=="metric":
                rows.append(f'<div class="m"><span class="mk">{esc(it["key"])}</span>'
                            f'<span class="mv">{esc(it["value"])}{esc(it.get("unit",""))}</span>'
                            + (f'<span class="mn">{esc(it["note"])}</span>' if it.get("note") else "")+'</div>')
            elif it["ev"]=="note":
                rows.append(f'<div class="nt">{esc(it["msg"])}</div>')
            elif it["ev"]=="curve":
                pts=it.get("points",[])
                if pts:
                    if any("score" in x for x in pts):
                        best=max(pts,key=lambda x:x.get("score",-1e9))
                    else:   # 旧 run 没记 score，用同样的记分规则重算
                        best=max(pts,key=lambda x:x["hit"]-(100-x["acc"])*6)
                    # 答对率区间窄，按 (v-88)/12 拉伸才看得出差异
                    def sc(v): return max(2,min(100,(v-88)/12*100))
                    rows.append('<div class="lg2"><span><i class="i1"></i>本地接住率</span>'
                                '<span><i class="i2"></i>本地答对率（88-100% 区间）</span></div>')
                    rows.append('<div class="crv">'+''.join(
                      f'<div class="cb{" sel" if p is best else ""}">'
                      f'<div class="pair"><div class="cbar b1" style="height:{p["hit"]}%" title="接住 {p["hit"]}%"></div>'
                      f'<div class="cbar b2" style="height:{sc(p["acc"])}%" title="答对 {p["acc"]}%"></div></div>'
                      f'<div class="cl">{p["th"]:.2f}</div></div>' for p in pts)+'</div>')
        body.append(f'''<div class="st {'bad' if not s['ok'] else ''}">
  <div class="sh"><span class="sn">{s['n']}</span><span class="stt">{esc(s['name'])}</span>
   {f'<span class="sd">{esc(s["desc"])}</span>' if s['desc'] else ''}
   <span class="se">{s['elapsed']}s</span></div>
  <div class="sb">{''.join(rows) or '<div class="nt">—</div>'}</div></div>''')

    final=""
    if end:
        tiles=[]
        def fmt(v):
            if isinstance(v,(int,float)):
                return str(int(round(v))) if abs(v-round(v))<0.05 or abs(v)>=10 else f"{v:.1f}"
            return str(v)
        for k,label,unit in [("gate","考卷成绩","%"),("local_hit","本地接住","%"),
                             ("gap","过拟合差距","pt"),("thresh","选定阈值","")]:
            if k in end:
                v = f"{end[k]:.2f}" if k=="thresh" else fmt(end[k])   # 阈值不取整
                tiles.append(f'<div class="tile"><div class="k">{label}</div>'
                             f'<div class="v">{v}{unit}</div></div>')
        if "promoted" in end:
            tiles.append(f'<div class="tile"><div class="k">本轮晋升</div>'
                         f'<div class="v">{"是" if end["promoted"] else "否"}</div></div>')
        final=f'<div class="tiles">{"".join(tiles)}</div>'

    return f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>E.V. {title}</title><style>
:root{{color-scheme:light;--bg:#f7f7f5;--sf:#fcfcfb;--bd:#e4e3df;--i1:#0b0b0b;--i2:#52514e;--i3:#87857e;--s1:#2a78d6;--s2:#eb6834;--ok:#0ca30c;--bad:#d03b3b}}
@media(prefers-color-scheme:dark){{:root{{--bg:#121211;--sf:#1a1a19;--bd:#33322f;--i1:#fff;--i2:#c3c2b7;--i3:#8d8c84;--s1:#3987e5;--s2:#d95926}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--i1);font:15px/1.7 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}}
.w{{max-width:900px;margin:0 auto;padding:44px 22px 70px}}
h1{{font-size:29px;margin:0 0 6px;letter-spacing:-.01em}}.sub{{color:var(--i2);margin:0 0 8px}}
.meta{{color:var(--i3);font-size:13px;margin-bottom:22px;font-variant-numeric:tabular-nums}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:0 0 28px}}
.tile{{background:var(--sf);border:1px solid var(--bd);border-radius:10px;padding:14px 16px}}
.tile .k{{color:var(--i3);font-size:12px;margin-bottom:4px}}.tile .v{{font-size:25px;font-weight:600;letter-spacing:-.02em}}
.st{{background:var(--sf);border:1px solid var(--bd);border-radius:11px;margin-bottom:12px;overflow:hidden}}
.st.bad{{border-color:var(--bad)}}
.sh{{display:flex;align-items:baseline;gap:10px;padding:13px 16px;border-bottom:1px solid var(--bd);flex-wrap:wrap}}
.sn{{width:22px;height:22px;border-radius:50%;background:var(--s1);color:#fff;font-size:12px;
 display:inline-flex;align-items:center;justify-content:center;flex:none}}
.stt{{font-weight:600}}.sd{{color:var(--i3);font-size:13px}}.se{{margin-left:auto;color:var(--i3);font-size:12.5px;font-variant-numeric:tabular-nums}}
.sb{{padding:11px 16px}}
.m{{display:flex;align-items:baseline;gap:9px;padding:4px 0;flex-wrap:wrap}}
.mk{{color:var(--i2);font-size:13.5px;min-width:130px}}
.mv{{font-weight:600;font-variant-numeric:tabular-nums}}
.mn{{color:var(--i3);font-size:12.5px}}
.nt{{color:var(--i2);font-size:13.5px;padding:2px 0;white-space:pre-wrap}}
.lg2{{display:flex;gap:14px;font-size:12px;color:var(--i2);margin:8px 0 2px}}
.lg2 i{{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px}}
.lg2 .i1{{background:var(--s1)}}.lg2 .i2{{background:var(--s2)}}
.crv{{display:flex;gap:6px;align-items:flex-end;height:110px;margin:6px 0 4px}}
.cb{{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%}}
.cb.sel .cl{{color:var(--s1);font-weight:700}}
.cb.sel{{background:color-mix(in srgb,var(--s1) 8%,transparent);border-radius:5px}}
.pair{{display:flex;gap:2px;align-items:flex-end;width:100%;height:100%}}
.cbar{{flex:1;border-radius:3px 3px 0 0;min-height:2px}}
.b1{{background:var(--s1)}}.b2{{background:var(--s2)}}
.cl{{color:var(--i3);font-size:10.5px;margin-top:4px;font-variant-numeric:tabular-nums}}
footer{{margin-top:34px;padding-top:16px;border-top:1px solid var(--bd);color:var(--i3);font-size:12.5px}}
</style></head><body><div class="w">
<h1>E.V. {title}</h1>
<p class="sub">{"只给一份能力清单，自动跑到可用状态" if kind=="bootstrap" else "从真实交互记录持续改进"}</p>
<p class="meta">{pathlib.Path(path).name}　·　共 {len(stages)} 个阶段　·　用时 {total}s</p>
{final}
{''.join(body)}
<footer>每个阶段都对应一个踩过的坑，已固化进流程 —— 用它的人不用重蹈。<br>
代码 <code>ev-poc/</code>　·　冷启动 <code>bootstrap.py</code>　·　日常 <code>daily.py</code></footer>
</div></body></html>'''

if __name__=="__main__":
    p = sys.argv[1] if len(sys.argv)>1 else None
    path, evs = load(p)
    out = BASE/"report.html"
    out.write_text(build(path,evs),"utf-8")
    print("已生成:", out)
