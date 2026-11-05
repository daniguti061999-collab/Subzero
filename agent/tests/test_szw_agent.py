"""Tests for the reference engine. Run:  python -m pytest tests -q   (or: python tests/test_szw_agent.py)"""
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
import szw_agent as A  # noqa: E402

AS_OF = date(2026, 10, 27)  # Tuesday


def test_truck_math():
    tue, thu = 2, 4
    # Delivery Thu 10/29 at a Tue-truck site with 2 days transit -> leaves Tue 10/27
    assert A.required_ship_date(date(2026, 10, 29), {"DateBasis": "D", "TransitCalendarDays": 2, "TruckWeekday": tue}) == date(2026, 10, 27)
    # Delivery Mon 11/02 at the Thu-truck site (arrives Mon, 4 calendar days) -> leaves Thu 10/29
    assert A.required_ship_date(date(2026, 11, 2), {"DateBasis": "D", "TransitCalendarDays": 4, "TruckWeekday": thu}) == date(2026, 10, 29)
    # Delivery Wed 10/28 at a Tue-truck site -> Tue 10/27 would arrive Thu (late) -> must leave Tue 10/20
    assert A.required_ship_date(date(2026, 10, 28), {"DateBasis": "D", "TransitCalendarDays": 2, "TruckWeekday": tue}) == date(2026, 10, 20)
    # Ship-date basis: ship by Fri 10/30 on a Thu truck -> Thu 10/29
    assert A.required_ship_date(date(2026, 10, 30), {"DateBasis": "S", "TransitCalendarDays": 4, "TruckWeekday": thu}) == date(2026, 10, 29)
    assert A.next_departures(AS_OF, tue) == (date(2026, 10, 27), date(2026, 11, 3))
    assert A.next_departures(AS_OF, tue, include_today=False) == (date(2026, 11, 3), date(2026, 11, 10))
    assert A.next_departures(AS_OF, thu) == (date(2026, 10, 29), date(2026, 11, 5))


def run_sample():
    out = Path(tempfile.mkdtemp())
    return A.run(ROOT / "sample_data", out, AS_OF), out


def test_statuses_and_quantities():
    r, _ = run_sample()
    by = {x["ReqKey"]: x for x in r["result"]["rows"]}
    assert "074101|1" not in by                                   # cancelled line excluded
    assert by["074120|1"]["Status"] == "On Track" and by["074120|1"]["ShortQty"] == 0   # ships on today's truck, FG 200 >= 150
    assert by["074098|1"]["Status"] == "Past Due" and by["074098|1"]["DaysPastDue"] == 5
    assert by["073950|3"]["Status"] == "Past Due" and by["073950|3"]["DaysPastDue"] == 14
    # SZ-2002: FG 300 (QH 50 excluded). Thu-truck line 10/29 nets first -> 200 short, Critical.
    assert by["074140|1"]["Status"] == "Critical" and by["074140|1"]["ShortQty"] == 200
    # Tue-truck line 11/03 -> nothing left -> 1,000 short, At Risk (truck after next)
    assert by["074133|2"]["Status"] == "At Risk" and by["074133|2"]["ShortQty"] == 1000
    assert by["074152|1"]["Status"] == "On Track"
    assert by["074160|1"]["Issues"] == "No truck schedule for ship-to"
    pdv = sum(x["PastDueValue"] for x in r["result"]["rows"])
    assert round(pdv, 2) == 4288.00                                # 300 x 12.40 + 80 x 7.10


def test_exceptions_and_dedup():
    r, out = run_sample()
    rules = sorted(e["RuleID"] for e in r["exceptions"])
    assert rules == ["D1", "D1", "R1", "R2", "R3", "R3", "R4", "R7", "R7", "R7"]
    keys = [a["ExceptionKey"] for a in r["alerts"]]
    assert "R3|073950|3|2026-10-13" not in keys                    # already acknowledged, not worse -> no repeat
    assert len(r["alerts"]) == 9
    reg = {x["ExceptionKey"]: x for x in r["register"]}
    assert reg["R1|074200|1|2026-10-27"]["Status"] == "Auto-cleared"
    r4 = next(e for e in r["exceptions"] if e["RuleID"] == "R4")
    assert "+27%" in r4["Detail"] and "WF-3150 (+80)" in r4["Detail"]
    assert (out / "daily_summary.md").exists() and (out / "alerts.json").exists()


def test_idempotent_second_run():
    """Running again on the same data with the new register sends nothing."""
    r1, out = run_sample()
    import shutil
    data2 = Path(tempfile.mkdtemp())
    for f in (ROOT / "sample_data").glob("*.csv"):
        shutil.copy(f, data2 / f.name)
    shutil.copy(out / "exceptions_register.csv", data2 / "exceptions_register.csv")
    r2 = A.run(data2, Path(tempfile.mkdtemp()), AS_OF)
    assert r2["alerts"] == []


def test_portal_export_with_syspro():
    """Raw Sub-Zero Open PO export (title rows, text dates) matched to SYSPRO SO lines."""
    import csv
    import openpyxl
    import import_subzero_openpo as I
    tmp = Path(tempfile.mkdtemp())
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Open Purchase Orders Subscripti"  # portal truncates to 31 chars
    ws["A1"] = "SubZero Open Purchase Orders"
    ws["A2"] = "Vendor: 007087-MILLS PRODUCTS INC"
    ws.append([])
    ws.append([])
    ws.append(["Order", "Line", "Release", "Item", "Whs", "Description", "Open Qty", "Due Date", "Buyer Email",
               "Message", "Your Ship Date", "Status"])
    ws.append(["P900001", 1, 0, "TEST-A", "22", "Part A", 500, "11/6/2026", "", "", "11/03", "Needs painted"])  # matched, 200 shipped
    ws.append(["P900002", 1, 0, "TEST-B", "10", "Part B", 300, "11/13/2026", "", "", "11/06", "Ready to ship"])  # not in SYSPRO
    ws.append(["P900003", 1, 0, "TEST-C", "23", "Part C", 100, "10/23/2026", "", "", "", ""])  # SYSPRO says all shipped
    wb.save(tmp / "portal.xlsx")
    fields = ["Customer", "CustomerPoNumber", "SalesOrder", "SalesOrderLine", "ReqKey", "StockCode", "ShipToKey",
              "OrderQty", "ShippedQty", "OpenQty", "OrderLineDate", "LineStatus"]
    with (tmp / "syspro.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerow(dict(zip(fields, ["SZW001", "P900001", "075001", "1", "075001|1", "TEST-A", "", "500", "200", "300", "2026-11-03", "Open"])))
        w.writerow(dict(zip(fields, ["SZW001", "P900003", "075003", "1", "075003|1", "TEST-C", "", "100", "100", "0", "2026-10-20", "Open"])))
        w.writerow(dict(zip(fields, ["SZW001", "P800999", "074999", "2", "074999|2", "TEST-D", "", "80", "0", "80", "2026-10-30", "Open"])))  # not on portal
    I.main(tmp / "portal.xlsx", tmp / "in", tmp / "syspro.csv")
    r = A.run(tmp / "in", tmp / "out", date(2026, 10, 28))
    by = {x["ReqKey"]: x for x in r["result"]["rows"]}
    assert by["P900001|1|0"]["OpenQty"] == 300 and by["P900001|1|0"]["MatchStatus"] == "Matched"
    assert by["P900001|1|0"]["Status"] == "Critical"            # not ready, next Tue truck 11/03
    assert by["P900002|1|0"]["MatchStatus"] == "NotInERP"
    assert by["P900002|1|0"]["ReqShipDate"] == "2026-11-06" and by["P900002|1|0"]["ReadyBy"] == "2026-11-05"  # loaded Thu
    rules = sorted(e["RuleID"] for e in r["exceptions"])
    assert rules.count("K1") == 1 and rules.count("K2") == 1
    c1 = [e for e in r["exceptions"] if e["RuleID"] == "C1"]
    assert [e["ReqKey"] for e in c1] == ["P900003|1|0"]           # 100 shipped per SYSPRO, still open at Sub-Zero


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
