import sys, time, urllib.request, statistics
label = sys.argv[1]
ids = ["ord-001","ord-002","ord-003","ord-004","ord-005"]
ts = []; err = 0
for i in range(25):
    url = "http://localhost:8000/order/" + ids[i % 5]
    t0 = time.time()
    try:
        r = urllib.request.urlopen(url, timeout=15); r.read()
        if r.status >= 300: err += 1
    except Exception as e:
        err += 1
    ts.append((time.time() - t0) * 1000)
s = sorted(ts)
p = lambda q: s[min(len(s)-1, int(len(s)*q))]
open(f"docs/gameday/results/lat_{label}.csv","w").write("\n".join(f"{x:.2f}" for x in ts))
print(f"  [{label:13}] avg={statistics.mean(ts):6.1f}ms  p50={p(.5):6.1f}ms  p95={p(.95):6.1f}ms  max={max(ts):6.1f}ms  errores={err}/25")
