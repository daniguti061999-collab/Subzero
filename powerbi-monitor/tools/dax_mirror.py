"""Literal Python mirror of the DAX calculated columns in Requirements.tmdl, to check them against the engine."""
import csv, sys, datetime as dt
D = sys.argv[1]; ASOF = dt.date(2026, 10, 28)
rd = lambda f: list(csv.DictReader(open(f"{D}/{f}", encoding="utf-8-sig")))
num = lambda v: float(v) if v not in ("", None) else None
dd = lambda v: dt.date.fromisoformat(v[:10]) if v else None
reqs = [r for r in rd("input/requirements.csv") if r["LineStatus"] != "Cancelled"]
sched = {s["ShipToKey"]: s for s in rd("input/shipto_schedule.csv") if s["Active"] != "0"}
ships = rd("input/shipments.csv"); fg = rd("input/fg_inventory.csv")
cfg = {r["Key"]: r["Value"] for r in rd("input/SZW_Config.csv")}
hol = {dt.date.fromisoformat(h) for h in cfg.get("Holidays", "").split(";") if h.strip()}
cal = [dt.date(2025, 1, 1) + dt.timedelta(i) for i in range((dt.date(2027, 12, 31) - dt.date(2025, 1, 1)).days + 1)]
biz = {d for d in cal if d.isoweekday() <= 5 and d not in hol}
eng = {r["ReqKey"]: r for r in rd("output/backlog_report.csv")}
def dmod(a, b): return a - b * (a // b)          # DAX MOD has the sign of the divisor (same as Python %)
rows = []
for r in reqs:
    s = sched.get(r["ShipToKey"]); line = dd(r["OrderLineDate"]); o = {"r": r}
    wd = int(s["TruckWeekday"]) if s else None
    if line is None: ship = None
    elif wd is None: ship = line
    else:
        latest = line - dt.timedelta(int(s["TransitCalendarDays"])) if s["DateBasis"] == "D" else line
        truck = latest - dt.timedelta(dmod(latest.isoweekday() - wd, 7))
        ship = max(d for d in cal if d <= truck and d in biz)
    o["ship"] = ship
    o["n1"] = ASOF + dt.timedelta(1) if wd is None else ASOF + dt.timedelta(dmod(wd - ASOF.isoweekday(), 7))
    o["n2"] = ASOF + dt.timedelta(7) if wd is None else o["n1"] + dt.timedelta(7)
    p = r["StockCode"]
    o["hasfg"] = any(f["StockCode"] == p and f["Warehouse"] != "QH" for f in fg)
    o["fga"] = sum(num(f["OnHandQty"]) or 0 for f in fg if f["StockCode"] == p and f["Warehouse"] != "QH")
    o["open"] = num(r["OpenQty"]) or 0; o["cust"] = num(r["CustomerOpenQty"]) or 0
    rows.append(o)
BIG = dt.date(9999, 12, 31)
for o in rows:
    p, d, k = o["r"]["StockCode"], o["ship"] or BIG, o["r"]["ReqKey"]
    o["cum"] = sum(x["open"] for x in rows if x["r"]["StockCode"] == p and ((x["ship"] or BIG) < d or ((x["ship"] or BIG) == d and x["r"]["ReqKey"] <= k)))
    netted = min(o["open"], max(0, o["cum"] - o["fga"]))
    rs = o["r"]["ReadyState"] or ""
    o["short"] = (0 if rs in ("Ready", "Unknown") else o["open"]) if (not o["hasfg"] and rs != "") else netted
    s = o["ship"]
    o["status"] = ("Complete" if o["open"] <= 0 else "Data Issue" if s is None else "Past Due" if s < ASOF else
                   "Critical" if o["short"] > 0 and s <= o["n1"] else "At Risk" if o["short"] > 0 and s <= o["n2"] else "On Track")
    last = max((dd(x["ShipDate"]) for x in ships if x["ReqKey"] == k), default=None)
    basis = last or s
    tr = int(sched[o["r"]["ShipToKey"]]["TransitCalendarDays"]) if o["r"]["ShipToKey"] in sched else 3
    o["snc"] = max(0, o["cust"] - o["open"])
    if basis:
        frm = min(basis, ASOF) + dt.timedelta(tr); arr = min(d for d in cal if d >= frm and d in biz)
        o["c1"] = o["snc"] > 0 and (ASOF - arr).days >= 1
    else: o["c1"] = False
    o["pdsz"] = dd(o["r"]["OrderLineDate"]) is not None and dd(o["r"]["OrderLineDate"]) < ASOF
    bd = len([d for d in cal if ASOF < d <= (s or ASOF) and d in biz])
    o["r8"] = rs == "NoMaterial" and o["status"] in ("On Track", "At Risk") and bd <= 40
S = lambda f: sum(f(o) for o in rows)
print("Past Due Qty", S(lambda o: o["open"] if o["status"] == "Past Due" else 0))
print("True Backlog Qty", S(lambda o: o["open"] if o["pdsz"] else 0))
print("SZ Past Due Qty", S(lambda o: o["cust"] if o["pdsz"] else 0), " SZ Open", S(lambda o: o["cust"]))
print("Critical Short", S(lambda o: o["short"] if o["status"] == "Critical" else 0), "At Risk Short", S(lambda o: o["short"] if o["status"] == "At Risk" else 0))
print("Shipped not credited", S(lambda o: o["snc"]), "C1 lines", S(lambda o: 1 if o["c1"] else 0))
print("Raw material risk", S(lambda o: o["open"] if o["r8"] else 0), "Unknown open lines", S(lambda o: 1 if (o["r"]["ReadyState"] == "Unknown" and o["open"] > 0) else 0))
mm = [(o["r"]["ReqKey"], o["status"], eng[o["r"]["ReqKey"]]["Status"]) for o in rows
      if o["status"] != eng[o["r"]["ReqKey"]]["Status"] or abs(o["short"] - float(eng[o["r"]["ReqKey"]]["ShortQty"])) > 1e-6]
print("Mismatch lines vs engine:", len(mm), mm[:5])
