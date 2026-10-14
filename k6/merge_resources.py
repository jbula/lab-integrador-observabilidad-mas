#!/usr/bin/env python3
"""Promedia docker stats de results/stats_<mode>.csv e inyecta cpu_pct/mem_mib en results_<mode>.json."""
import json, re, statistics
from pathlib import Path
RES = Path(__file__).parent / "results"

def to_mib(s):
    s=s.strip()
    m=re.match(r"([\d.]+)\s*([KMG]i?B)", s)
    if not m: return 0.0
    v=float(m.group(1)); u=m.group(2)
    return {"KiB":v/1024,"MiB":v,"GiB":v*1024,"KB":v/1024,"MB":v,"GB":v*1024,"B":v/1048576}.get(u,v)

def summarize(mode):
    f=RES/f"stats_{mode}.csv"
    cpu=[]; mem=[]
    if not f.exists(): return None
    for line in f.read_text().splitlines():
        parts=line.split(",")
        if len(parts)<3: continue
        name,cp,mu=parts[0],parts[1],parts[2]
        try: cpu.append(float(cp.replace("%","")))
        except: pass
        mem.append(to_mib(mu.split("/")[0]))
    # cada muestra tiene 3 contenedores; sumamos por timestamp aproximando: promedio total
    return {"cpu_pct": round(sum(cpu)/max(len(cpu),1)*3,2),   # ~suma de los 3 contenedores
            "mem_mib": round(sum(mem)/max(len(mem),1)*3,1)}

for mode in ("baseline","otel"):
    jf=RES/f"results_{mode}.json"
    agg=summarize(mode)
    if jf.exists() and agg:
        d=json.loads(jf.read_text()); d["metrics"].update(agg); jf.write_text(json.dumps(d,indent=2))
        print(f"  {mode}: CPU~{agg['cpu_pct']}%  Mem~{agg['mem_mib']}MiB (suma de 3 contenedores)")
    else:
        print(f"  {mode}: faltan datos (json={jf.exists()}, stats={agg is not None})")
