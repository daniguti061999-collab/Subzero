"""
Mills Products — Sub-Zero/Wolf Shipment & Backlog Agent: reference engine.

What it is
    The exact business logic of the agent, runnable on CSV extracts that have the
    same columns as the SQL views in ../sql/01_szw_views.sql. Use it to:
      1. check the Power BI DAX gives the same numbers (same inputs -> same outputs),
      2. run the parallel run against Robert and Ricardo's manual backlog report,
      3. run the agent end to end before the Power Automate flows exist.

What it never does
    It reads files and writes files. It does not change SYSPRO, orders, schedules,
    inventory or shipments.

Run
    python szw_agent.py --data ../sample_data --out ../sample_output --as-of 2026-10-27
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

SEVERITY_RANK = {"Info": 0, "Warning": 1, "Predictive": 1, "Critical": 2, "Escalation": 3, "System": 1}
STATUS_TO_RULE = {"Past Due": ("R3", "Critical"), "Critical": ("R2", "Critical"),
                  "At Risk": ("R1", "Warning"), "Data Issue": ("D1", "System")}


# ----------------------------------------------------------------------------- io
def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0].keys()) if rows else [])
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def d(s: str) -> date | None:
    return date.fromisoformat(s.strip()[:10]) if s and s.strip() else None


def num(s) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


# ----------------------------------------------------------------------- trucks
def latest_truck_on_or_before(x: date, truck_weekday: int) -> date:
    """Latest date <= x that falls on the truck weekday (ISO: Mon=1 .. Sun=7)."""
    return x - timedelta(days=(x.isoweekday() - truck_weekday) % 7)


def next_departures(as_of: date, truck_weekday: int, include_today: bool = True) -> tuple[date, date]:
    first = as_of + timedelta(days=(truck_weekday - as_of.isoweekday()) % 7)
    if first == as_of and not include_today:
        first += timedelta(days=7)
    return first, first + timedelta(days=7)


def prev_business_day(x: date, holidays: frozenset = frozenset()) -> date:
    """x itself if it is a Mon-Fri non-holiday, else the business day before it."""
    while x.isoweekday() > 5 or x in holidays:
        x -= timedelta(days=1)
    return x


def next_business_day(x: date, holidays: frozenset = frozenset()) -> date:
    while x.isoweekday() > 5 or x in holidays:
        x += timedelta(days=1)
    return x


def required_ship_date(line_date: date, sched: dict | None, holidays: frozenset = frozenset()) -> date | None:
    """Truck departure that satisfies the date keyed on the order line.
    A truck that falls on a plant holiday leaves the business day before."""
    if line_date is None:
        return None
    if sched is None:
        return line_date                       # no schedule: use the line date as-is (flagged)
    if sched["DateBasis"] == "D":              # order date = delivery date at the customer
        latest_departure = line_date - timedelta(days=int(sched["TransitCalendarDays"]))
    else:                                      # order date = ship date
        latest_departure = line_date
    return prev_business_day(latest_truck_on_or_before(latest_departure, int(sched["TruckWeekday"])), holidays)


def arrival_date(ship: date, sched: dict | None, holidays: frozenset = frozenset()) -> date:
    days = int(sched["TransitCalendarDays"]) if sched else 3
    return next_business_day(ship + timedelta(days=days), holidays)


def aging_bucket(days: int) -> str:
    if days <= 0:
        return "Not past due"
    if days <= 2:
        return "1-2 days"
    if days <= 7:
        return "3-7 days"
    if days <= 14:
        return "8-14 days"
    return "15+ days"


# ------------------------------------------------------------------------ model
@dataclass
class Config:
    backlog_growth_pct: float = 0.10
    demand_change_pct: float = 0.15
    pull_in_workdays: int = 10
    include_today_truck: bool = True
    hold_warehouses: set = field(default_factory=set)
    holidays: frozenset = frozenset()
    material_risk_workdays: int = 40        # 8-week raw-material lead time
    credit_grace_days: int = 1              # days after arrival before C1 fires
    routing: dict = field(default_factory=dict)   # RuleID -> list of emails
    escalation: dict = field(default_factory=dict)

    @classmethod
    def load(cls, folder: Path) -> "Config":
        cfg = cls()
        for row in read_csv(folder / "SZW_Config.csv"):
            k, v = row["Key"], row["Value"]
            if k == "BacklogGrowthPct":
                cfg.backlog_growth_pct = num(v)
            elif k == "DemandChangePct":
                cfg.demand_change_pct = num(v)
            elif k == "PullInWorkdays":
                cfg.pull_in_workdays = int(num(v))
            elif k == "IncludeTodayTruck":
                cfg.include_today_truck = v.strip().lower() in ("1", "true", "yes")
            elif k == "Holidays":
                cfg.holidays = frozenset(date.fromisoformat(h.strip()) for h in v.split(";") if h.strip())
            elif k == "MaterialRiskWorkdays":
                cfg.material_risk_workdays = int(num(v))
            elif k == "CreditGraceDays":
                cfg.credit_grace_days = int(num(v))
            elif k == "HoldWarehouses":
                cfg.hold_warehouses = {w.strip() for w in v.split(";") if w.strip()}
        for row in read_csv(folder / "SZW_Routing.csv"):
            cfg.routing[row["RuleID"]] = [e.strip() for e in row["NotifyEmails"].split(";") if e.strip()]
            cfg.escalation[row["RuleID"]] = [e.strip() for e in row["EscalateEmails"].split(";") if e.strip()]
        return cfg


def business_days_between(a: date, b: date) -> int:
    """Mon-Fri days in (a, b]; negative if b < a."""
    sign = 1 if b >= a else -1
    lo, hi = (a, b) if b >= a else (b, a)
    n, cur = 0, lo
    while cur < hi:
        cur += timedelta(days=1)
        if cur.isoweekday() <= 5:
            n += 1
    return sign * n


def evaluate(data: Path, as_of: date, cfg: Config) -> dict:
    reqs = read_csv(data / "requirements.csv")
    ships = read_csv(data / "shipments.csv")
    inv = read_csv(data / "fg_inventory.csv")
    sched = {r["ShipToKey"]: r for r in read_csv(data / "shipto_schedule.csv") if r.get("Active", "1") in ("1", "True", "true")}

    # FG available per part = on hand outside quality-hold warehouses
    fg: dict[str, float] = {}
    for r in inv:
        if r["Warehouse"] in cfg.hold_warehouses:
            continue
        fg[r["StockCode"]] = fg.get(r["StockCode"], 0.0) + num(r["OnHandQty"])

    shipped_by_req: dict[str, float] = {}
    last_ship: dict[str, date] = {}
    for s in ships:
        shipped_by_req[s["ReqKey"]] = shipped_by_req.get(s["ReqKey"], 0.0) + num(s["ShipQty"])
        sd = d(s["ShipDate"])
        if sd and (s["ReqKey"] not in last_ship or sd > last_ship[s["ReqKey"]]):
            last_ship[s["ReqKey"]] = sd
    req_keys = {r["ReqKey"] for r in reqs}
    unmatched = [s for s in ships if s["ReqKey"] not in req_keys]

    rows = []
    for r in reqs:
        if r.get("LineStatus", "Open") == "Cancelled":
            continue
        st = sched.get(r["ShipToKey"])
        ship_date = required_ship_date(d(r["OrderLineDate"]), st, cfg.holidays)
        open_qty = max(0.0, num(r["OpenQty"]))
        issues = []
        if st is None:
            issues.append("No truck schedule for ship-to")
        if ship_date is None:
            issues.append("Missing order line date")
        if num(r["ShippedQty"]) < 0 or num(r["ShippedQty"]) > num(r["OrderQty"]):
            issues.append("Shipped qty outside 0..ordered")
        if r.get("DataNote"):
            issues.append(r["DataNote"])
        rows.append({
            **r,
            "ReqShipDate": ship_date.isoformat() if ship_date else "",
            "OpenQty": open_qty,
            "ShippedQtyFromShipments": shipped_by_req.get(r["ReqKey"], 0.0),
            "Truck": f"{['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][int(st['TruckWeekday'])-1]} truck" if st else "",
            "ReadyState": r.get("ReadyState", ""),
            "MatchStatus": r.get("MatchStatus", ""),
            "ReadyBy": (prev_business_day(ship_date - timedelta(days=int(num(st.get("LoadDaysBefore")))), cfg.holidays).isoformat()
                        if ship_date and st and num(st.get("LoadDaysBefore")) > 0 else (ship_date.isoformat() if ship_date else "")),
            "LastShipDate": last_ship[r["ReqKey"]].isoformat() if r["ReqKey"] in last_ship else "",
            "_ship": ship_date, "_sched": st, "_issues": issues,
        })

    # Netting: per part, in ship-date order (past due first), FG covers earliest first
    rows.sort(key=lambda x: (x["StockCode"], x["_ship"] or date.max, x["ReqKey"]))
    cum: dict[str, float] = {}
    for x in rows:
        p = x["StockCode"]
        cum[p] = cum.get(p, 0.0) + x["OpenQty"]
        x["FGAvailable"] = fg.get(p, 0.0)
        x["CumOpenByPart"] = cum[p]
        x["ShortQty"] = min(x["OpenQty"], max(0.0, cum[p] - x["FGAvailable"]))
        # No FG figure for the part but a production status from the plan:
        # Ready (or unknown) = covered, anything still to make = short.
        if p not in fg and x["ReadyState"]:
            x["ShortQty"] = 0.0 if x["ReadyState"] in ("Ready", "Unknown") else x["OpenQty"]

    for x in rows:
        ship, st = x["_ship"], x["_sched"]
        dpd = (as_of - ship).days if ship and ship < as_of and x["OpenQty"] > 0 else 0
        x["DaysPastDue"] = dpd
        x["Aging"] = aging_bucket(dpd)
        x["PastDueValue"] = round(x["OpenQty"] * num(x.get("UnitPrice")), 2) if dpd > 0 else 0.0
        if st:
            n1, n2 = next_departures(as_of, int(st["TruckWeekday"]), cfg.include_today_truck)
        else:
            n1, n2 = as_of + timedelta(days=1), as_of + timedelta(days=7)
        x["NextTruck"] = n1.isoformat()
        if x["OpenQty"] <= 0:
            status = "Complete"
        elif ship is None or (x["_issues"] and "Missing order line date" in x["_issues"]):
            status = "Data Issue"
        elif ship < as_of:
            status = "Past Due"
        elif x["ShortQty"] > 0 and ship <= n1:
            status = "Critical"
        elif x["ShortQty"] > 0 and ship <= n2:
            status = "At Risk"
        else:
            status = "On Track"
        x["Status"] = status
        x["Issues"] = "; ".join(x["_issues"])

    return {"rows": rows, "unmatched": unmatched, "fg": fg}


# --------------------------------------------------------------------- exceptions
def build_exceptions(result: dict, as_of: date, cfg: Config, data: Path) -> list[dict]:
    ex = []
    for x in result["rows"]:
        if x["Status"] in STATUS_TO_RULE:
            rule, sev = STATUS_TO_RULE[x["Status"]]
            ex.append({"RuleID": rule, "Severity": sev, "ReqKey": x["ReqKey"], "Part": x["StockCode"],
                       "Customer": x["Customer"], "ShipTo": x["ShipToKey"], "ReqShipDate": x["ReqShipDate"],
                       "OpenQty": x["OpenQty"], "ShortQty": x["ShortQty"], "DaysPastDue": x["DaysPastDue"],
                       "FGAvailable": x["FGAvailable"], "Truck": x["Truck"], "Detail": x["Issues"]})
        elif x["Issues"]:
            ex.append({"RuleID": "D1", "Severity": "System", "ReqKey": x["ReqKey"], "Part": x["StockCode"],
                       "Customer": x["Customer"], "ShipTo": x["ShipToKey"], "ReqShipDate": x["ReqShipDate"],
                       "OpenQty": x["OpenQty"], "ShortQty": 0, "DaysPastDue": 0, "FGAvailable": x["FGAvailable"],
                       "Truck": x["Truck"], "Detail": x["Issues"]})
        if x["Status"] in STATUS_TO_RULE and x["Issues"] and x["Status"] != "Data Issue":
            ex[-1]["Detail"] = x["Issues"]
        # R8 raw-material risk: line still needs material and its truck is inside the lead time
        if (x["ReadyState"] == "NoMaterial" and x["Status"] in ("On Track", "At Risk") and x["_ship"]
                and business_days_between(as_of, x["_ship"]) <= cfg.material_risk_workdays):
            ex.append({"RuleID": "R8", "Severity": "Warning", "ReqKey": x["ReqKey"], "Part": x["StockCode"],
                       "Customer": x["Customer"], "ShipTo": x["ShipToKey"], "ReqShipDate": x["ReqShipDate"],
                       "OpenQty": x["OpenQty"], "ShortQty": x["OpenQty"], "DaysPastDue": 0,
                       "FGAvailable": x["FGAvailable"], "Truck": x["Truck"],
                       "Detail": f"raw material not available; truck in {business_days_between(as_of, x['_ship'])} workdays"})
        # C1 customer credit: Mills shipped, the customer still shows the qty open after arrival
        cust_open = num(x.get("CustomerOpenQty"))
        # ship date from the shipment record; if SYSPRO shipments are not matched to this line yet,
        # fall back to the planned truck (the qty is no longer open in SYSPRO, so it has shipped by then)
        basis = d(x["LastShipDate"]) or x["_ship"]
        if cust_open > x["OpenQty"] and basis:
            arr = arrival_date(min(basis, as_of), x["_sched"], cfg.holidays)
            if (as_of - arr).days >= cfg.credit_grace_days:
                ex.append({"RuleID": "C1", "Severity": "Warning", "ReqKey": x["ReqKey"], "Part": x["StockCode"],
                           "Customer": x["Customer"], "ShipTo": x["ShipToKey"], "ReqShipDate": x["ReqShipDate"],
                           "OpenQty": cust_open - x["OpenQty"], "ShortQty": 0, "DaysPastDue": (as_of - arr).days,
                           "FGAvailable": x["FGAvailable"], "Truck": x["Truck"],
                           "Detail": f"{cust_open - x['OpenQty']:,.0f} pcs shipped {x['LastShipDate'] or 'per SYSPRO'} (arrived ~{arr.isoformat()}) "
                                     f"still open on the customer's PO list"})
    for s in result["unmatched"]:
        ex.append({"RuleID": "D1", "Severity": "System", "ReqKey": s["ReqKey"], "Part": s["StockCode"],
                   "Customer": s.get("Customer", ""), "ShipTo": "", "ReqShipDate": s["ShipDate"],
                   "OpenQty": 0, "ShortQty": 0, "DaysPastDue": 0, "FGAvailable": 0, "Truck": "",
                   "Detail": f"Unmatched shipment {s['ShipmentNo']} qty {s['ShipQty']}"})

    # K1 customer PO line not keyed in SYSPRO; K2 open in SYSPRO but gone from the customer's list
    for x in result["rows"]:
        if x.get("MatchStatus") == "NotInERP" and num(x.get("CustomerOpenQty")) > 0:
            ex.append({"RuleID": "K1", "Severity": "Warning", "ReqKey": x["ReqKey"], "Part": x["StockCode"],
                       "Customer": x["Customer"], "ShipTo": x["ShipToKey"], "ReqShipDate": x["ReqShipDate"],
                       "OpenQty": num(x.get("CustomerOpenQty")), "ShortQty": 0, "DaysPastDue": 0,
                       "FGAvailable": x["FGAvailable"], "Truck": x["Truck"],
                       "Detail": f"customer PO {x.get('CustomerPoNumber', '')} item {x['StockCode']} is not on a SYSPRO sales order"})
    for k in read_csv(data / "erp_only_lines.csv"):
        ex.append({"RuleID": "K2", "Severity": "Warning", "ReqKey": k["ReqKey"], "Part": k["StockCode"],
                   "Customer": k.get("Customer", ""), "ShipTo": k.get("ShipToKey", ""), "ReqShipDate": k.get("OrderLineDate", ""),
                   "OpenQty": num(k["OpenQty"]), "ShortQty": 0, "DaysPastDue": 0, "FGAvailable": 0, "Truck": "",
                   "Detail": f"SYSPRO SO line open ({num(k['OpenQty']):,.0f} pcs, PO {k.get('CustomerPoNumber', '')}) "
                             "but not on the customer's open PO list"})

    # R4 backlog growth vs the previous snapshot (customer group level)
    prev = read_csv(data / "previous_snapshot.csv")
    past_due_now = sum(x["OpenQty"] for x in result["rows"] if x["Status"] == "Past Due")
    if prev:
        prev_pd = sum(num(p["PastDueQty"]) for p in prev)
        if prev_pd > 0 and (past_due_now - prev_pd) / prev_pd > cfg.backlog_growth_pct:
            contrib: dict[str, float] = {}
            prev_by_part = {p["StockCode"]: num(p["PastDueQty"]) for p in prev}
            for x in result["rows"]:
                if x["Status"] == "Past Due":
                    contrib[x["StockCode"]] = contrib.get(x["StockCode"], 0) + x["OpenQty"]
            deltas = sorted(((k, v - prev_by_part.get(k, 0)) for k, v in contrib.items()), key=lambda t: -t[1])
            ex.append({"RuleID": "R4", "Severity": "Warning", "ReqKey": "Sub-Zero/Wolf", "Part": "",
                       "Customer": "Sub-Zero/Wolf", "ShipTo": "", "ReqShipDate": as_of.isoformat(),
                       "OpenQty": past_due_now, "ShortQty": 0, "DaysPastDue": 0, "FGAvailable": 0, "Truck": "",
                       "Detail": f"Past due {past_due_now:,.0f} vs {prev_pd:,.0f} "
                                 f"(+{(past_due_now - prev_pd) / prev_pd:.0%}). Top: "
                                 + ", ".join(f"{k} (+{v:,.0f})" for k, v in deltas[:3] if v > 0)})

    # R7 demand change vs the previous requirements snapshot
    prev_req = {p["ReqKey"]: p for p in read_csv(data / "previous_requirements.csv")}
    for x in result["rows"]:
        p = prev_req.get(x["ReqKey"])
        if not p:
            continue
        q0, q1 = num(p["OrderQty"]), num(x["OrderQty"])
        d0, d1 = d(p["OrderLineDate"]), d(x["OrderLineDate"])
        msgs = []
        if q0 > 0 and (q1 - q0) / q0 > cfg.demand_change_pct:
            msgs.append(f"qty {q0:,.0f} -> {q1:,.0f} (+{(q1 - q0) / q0:.0%})")
        if d0 and d1 and d1 < d0 and business_days_between(as_of, d1) <= cfg.pull_in_workdays:
            msgs.append(f"date pulled in {d0} -> {d1}")
        if msgs:
            ex.append({"RuleID": "R7", "Severity": "Warning", "ReqKey": x["ReqKey"], "Part": x["StockCode"],
                       "Customer": x["Customer"], "ShipTo": x["ShipToKey"], "ReqShipDate": x["ReqShipDate"],
                       "OpenQty": x["OpenQty"], "ShortQty": x["ShortQty"], "DaysPastDue": 0,
                       "FGAvailable": x["FGAvailable"], "Truck": x["Truck"], "Detail": "; ".join(msgs)})

    for e in ex:
        e["ExceptionKey"] = f"{e['RuleID']}|{e['ReqKey']}|{e['ReqShipDate']}"
    return ex


def reconcile_register(current: list[dict], register: list[dict], as_of: date) -> tuple[list[dict], list[dict]]:
    """Merge today's exceptions into the register. Returns (new register, notifications)."""
    reg = {r["ExceptionKey"]: dict(r) for r in register}
    notify = []
    seen = set()
    for e in current:
        k = e["ExceptionKey"]
        seen.add(k)
        old = reg.get(k)
        if old is None or old.get("Status") in ("Resolved", "Auto-cleared"):
            reg[k] = {**e, "Status": "New", "FirstDetected": as_of.isoformat(), "LastSeen": as_of.isoformat(),
                      "LastNotified": as_of.isoformat(), "EscalationLevel": 0}
            notify.append({**e, "Reason": "New"})
            continue
        worse = (SEVERITY_RANK.get(e["Severity"], 0) > SEVERITY_RANK.get(old.get("Severity", ""), 0)
                 or num(e["ShortQty"]) > 1.2 * num(old.get("ShortQty", 0)) > 0)
        reg[k] = {**old, **{f: e[f] for f in ("Severity", "OpenQty", "ShortQty", "DaysPastDue", "FGAvailable", "Detail")},
                  "LastSeen": as_of.isoformat()}
        if worse:
            reg[k]["LastNotified"] = as_of.isoformat()
            notify.append({**e, "Reason": "Worse"})
    for k, r in reg.items():
        if k not in seen and r.get("Status") in ("New", "Acknowledged", "Recovery planned"):
            r["Status"] = "Auto-cleared"
            r["ClearedAt"] = as_of.isoformat()
    return list(reg.values()), notify


# -------------------------------------------------------------------- messages
def message(e: dict) -> str:
    q = lambda v: f"{num(v):,.0f}"
    if e["RuleID"] == "R3":
        return (f"[CRITICAL] Part {e['Part']} - SO line {e['ReqKey']} missed the {e['ReqShipDate']} {e['Truck']} "
                f"with {q(e['OpenQty'])} units open ({e['DaysPastDue']} day(s) past due). FG available now: {q(e['FGAvailable'])}. "
                "Review inventory, production completion dates and recovery shipment options.")
    if e["RuleID"] == "R2":
        return (f"[CRITICAL] Part {e['Part']} - projected {q(e['ShortQty'])}-unit shortage for the {e['ReqShipDate']} {e['Truck']} "
                f"({q(e['OpenQty'])} required, {q(e['FGAvailable'])} FG on hand for all open lines). "
                "Review production recovery options and record a recovery plan.")
    if e["RuleID"] == "R1":
        return (f"[WARNING] Part {e['Part']} - projected {q(e['ShortQty'])}-unit shortage for the {e['ReqShipDate']} {e['Truck']}.")
    if e["RuleID"] == "R4":
        return f"[WARNING] Sub-Zero/Wolf past-due backlog grew. {e['Detail']}."
    if e["RuleID"] == "R8":
        return (f"[WARNING] Part {e['Part']} - SO line {e['ReqKey']} for the {e['ReqShipDate']} {e['Truck']} "
                f"({q(e['OpenQty'])} pcs): {e['Detail']}. Confirm the material order date.")
    if e["RuleID"] == "C1":
        return (f"[ACTION] Part {e['Part']} - PO line {e['ReqKey']}: {e['Detail']}. "
                "Ask the customer to receive or apply the shipment so their past-due report is correct.")
    if e["RuleID"] == "K1":
        return (f"[ACTION] {e['Part']} - {e['Detail']} ({q(e['OpenQty'])} pcs, truck {e['ReqShipDate']}). "
                "Key the PO into SYSPRO so it is planned and shipped.")
    if e["RuleID"] == "K2":
        return (f"[CHECK] {e['Part']} - {e['Detail']}. Confirm with the customer and close or update the SO line.")
    if e["RuleID"] == "R7":
        return f"[WARNING] Demand change on {e['Part']} (SO line {e['ReqKey']}): {e['Detail']}."
    return f"[SYSTEM] {e['Part'] or ''} {e['ReqKey']}: {e['Detail']}"


def adaptive_card(e: dict) -> dict:
    color = {"Critical": "Attention", "Warning": "Warning"}.get(e["Severity"], "Default")
    return {
        "type": "AdaptiveCard", "version": "1.4",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "body": [
            {"type": "TextBlock", "text": f"{e['Severity'].upper()} - {e['RuleID']} - {e['Part'] or e['Customer']}",
             "weight": "Bolder", "color": color, "size": "Medium"},
            {"type": "TextBlock", "text": message(e), "wrap": True},
            {"type": "FactSet", "facts": [
                {"title": "SO line", "value": str(e["ReqKey"])},
                {"title": "Ship date / truck", "value": f"{e['ReqShipDate']} {e['Truck']}".strip()},
                {"title": "Open qty", "value": f"{num(e['OpenQty']):,.0f}"},
                {"title": "Short qty", "value": f"{num(e['ShortQty']):,.0f}"}]},
        ],
        "actions": [{"type": "Action.OpenUrl", "title": "Open exception", "url": "{{ExceptionItemUrl}}"},
                    {"type": "Action.OpenUrl", "title": "View in Power BI", "url": "{{ReportUrl}}"}],
    }


def daily_summary(result: dict, register: list[dict], notify: list[dict], as_of: date) -> str:
    rows = result["rows"]
    pd_rows = [x for x in rows if x["Status"] == "Past Due"]
    crit = [x for x in rows if x["Status"] == "Critical"]
    risk = [x for x in rows if x["Status"] == "At Risk"]
    due_today = [x for x in rows if x["ReqShipDate"] == as_of.isoformat() and x["OpenQty"] > 0]
    lines = [f"# Sub-Zero/Wolf daily backlog summary - {as_of.isoformat()}", "",
             f"- Past-due backlog: {sum(x['OpenQty'] for x in pd_rows):,.0f} units on {len(pd_rows)} lines "
             f"(${sum(x['PastDueValue'] for x in pd_rows):,.0f})",
             f"- Shipping today: {sum(x['OpenQty'] for x in due_today):,.0f} units on {len(due_today)} lines",
             f"- Critical (short on the next truck): {len(crit)} lines, {sum(x['ShortQty'] for x in crit):,.0f} units short",
             f"- At risk (short on the truck after): {len(risk)} lines, {sum(x['ShortQty'] for x in risk):,.0f} units short",
             f"- Shipped but still open on the customer's list (C1): "
             f"{sum(num(x.get('CustomerOpenQty')) - x['OpenQty'] for x in rows if num(x.get('CustomerOpenQty')) > x['OpenQty']):,.0f} pcs",
             f"- Lines with no production status (readiness unknown, treated as covered): "
             f"{sum(1 for x in rows if x['ReadyState'] == 'Unknown' and x['OpenQty'] > 0)}",
             f"- New or worse exceptions today: {len(notify)}; open in register: "
             f"{sum(1 for r in register if r.get('Status') in ('New', 'Acknowledged', 'Recovery planned'))}", "",
             "| Status | Part | SO line | Ship date | Truck | Open | Short | Days past due |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    order = {"Past Due": 0, "Critical": 1, "At Risk": 2, "Data Issue": 3}
    for x in sorted((x for x in rows if x["Status"] in order), key=lambda x: (order[x["Status"]], -x["DaysPastDue"])):
        lines.append(f"| {x['Status']} | {x['StockCode']} | {x['ReqKey'].replace('|', '/')} | {x['ReqShipDate']} | {x['Truck']} | "
                     f"{x['OpenQty']:,.0f} | {x['ShortQty']:,.0f} | {x['DaysPastDue']} |")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------- main
def run(data: Path, out: Path, as_of: date) -> dict:
    cfg = Config.load(data)
    result = evaluate(data, as_of, cfg)
    current = build_exceptions(result, as_of, cfg, data)
    register, notify = reconcile_register(current, read_csv(data / "exceptions_register.csv"), as_of)
    alerts = [{"ExceptionKey": e["ExceptionKey"], "RuleID": e["RuleID"], "Severity": e["Severity"],
               "Reason": e["Reason"], "To": cfg.routing.get(e["RuleID"], []), "Message": message(e),
               "Card": adaptive_card(e)} for e in notify]

    report_fields = ["Status", "Customer", "ShipToKey", "StockCode", "SalesOrder", "SalesOrderLine", "ReqKey",
                     "CustomerPoNumber", "OrderLineDate", "ReqShipDate", "Truck", "OrderQty", "ShippedQty", "OpenQty",
                     "FGAvailable", "ReadyState", "CumOpenByPart", "ShortQty", "DaysPastDue", "Aging", "PastDueValue",
                     "CustomerOpenQty", "LastShipDate", "ReadyBy", "MatchStatus", "Notes", "Issues"]
    write_csv(out / "backlog_report.csv", result["rows"], report_fields)
    write_csv(out / "exceptions_register.csv", register,
              ["ExceptionKey", "RuleID", "Severity", "Status", "Part", "Customer", "ShipTo", "ReqKey", "ReqShipDate",
               "Truck", "OpenQty", "ShortQty", "DaysPastDue", "FGAvailable", "Detail", "FirstDetected", "LastSeen",
               "LastNotified", "ClearedAt", "EscalationLevel"])
    snap = {}
    for x in result["rows"]:
        if x["Status"] == "Past Due":
            snap[x["StockCode"]] = snap.get(x["StockCode"], 0) + x["OpenQty"]
    write_csv(out / f"snapshot_{as_of.isoformat()}.csv",
              [{"SnapshotDate": as_of.isoformat(), "StockCode": k, "PastDueQty": v} for k, v in sorted(snap.items())])
    (out / "alerts.json").write_text(json.dumps(alerts, indent=2), encoding="utf-8")
    (out / "daily_summary.md").write_text(daily_summary(result, register, notify, as_of), encoding="utf-8")
    return {"result": result, "exceptions": current, "register": register, "alerts": alerts}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    a = ap.parse_args()
    r = run(a.data, a.out, a.as_of)
    print(f"{len(r['result']['rows'])} requirement lines, {len(r['exceptions'])} exceptions, {len(r['alerts'])} alerts -> {a.out}")
