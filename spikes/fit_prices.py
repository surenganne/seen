"""Phase 0/P1-6: infer per-token prices from Claude Code's native cost-state.

Assumes the published ratios (cache read 0.1x input, 5m write 1.25x, 1h write 2x)
and solves the two remaining unknowns (input, output $/MTok) by least squares,
then reports the residual per session. Usage: python3 spikes/fit_prices.py <transcript.jsonl>...
"""
import glob
import json
import sys


def totals(path):
    seen, t, cost = set(), dict(i=0, o=0, cr=0, c5=0, c1=0), None
    files = [path] + glob.glob(path[:-6] + "/subagents/*.jsonl")
    for f in files:
        for ln in open(f):
            d = json.loads(ln)
            if d.get("type") == "cost-state" and f == path:
                cost = sum(m["costUSD"] for m in d["modelUsage"].values())
            m = d.get("message") or {}
            if d.get("type") == "assistant" and m.get("id") not in seen:
                seen.add(m.get("id"))
                u = m.get("usage") or {}
                cc = u.get("cache_creation") or {}
                t["i"] += u.get("input_tokens", 0)
                t["o"] += u.get("output_tokens", 0)
                t["cr"] += u.get("cache_read_input_tokens", 0)
                t["c5"] += cc.get("ephemeral_5m_input_tokens", 0)
                t["c1"] += cc.get("ephemeral_1h_input_tokens", 0)
    return t, cost


rows = []
for p in sys.argv[1:]:
    t, cost = totals(p)
    if cost:
        x = (t["i"] + 0.1 * t["cr"] + 1.25 * t["c5"] + 2 * t["c1"]) / 1e6
        rows.append((x, t["o"] / 1e6, cost, p))
# normal equations for cost = a*x + b*y
sxx = sum(r[0] ** 2 for r in rows); syy = sum(r[1] ** 2 for r in rows); sxy = sum(r[0] * r[1] for r in rows)
sxc = sum(r[0] * r[2] for r in rows); syc = sum(r[1] * r[2] for r in rows)
det = sxx * syy - sxy ** 2
a = (sxc * syy - syc * sxy) / det
b = (syc * sxx - sxc * sxy) / det
print(f"input ${a:.4f}/MTok  output ${b:.4f}/MTok  over {len(rows)} sessions")
for x, y, c, p in rows:
    print(f"  {p.rsplit('/', 1)[-1][:40]:40} native={c:.6f} fitted={a * x + b * y:.6f} err={(a * x + b * y - c) / c * 100:+.3f}%")
