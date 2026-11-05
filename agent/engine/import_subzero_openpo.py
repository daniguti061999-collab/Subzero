"""
Convert the Sub-Zero "Open Purchase Orders Subscription" sheet (as used in the
backlog recovery workbook) into the agent's input files.

    python import_subzero_openpo.py "<workbook>.xlsx" --out ../data_real_2026-10-28/input

What comes from where
    Sub-Zero portal columns  -> demand: Order, Line, Release, Item, Whs, Open Qty, Due Date
    Mills columns in the plan -> what Mills shipped (Ship Date to Subzero, Qty Shipped) and
                                 production status ("Ready to ship", "Needs painted", ...)
    Later, shipments and stock come from SYSPRO (sql/01_szw_views.sql) instead of the plan.

Ship-to rules found in the plan (Oct 28, 2026):
    Whs 22 and 23 ship Tuesday, arrive Friday (3 calendar days).
    Whs 10 ships Friday, arrives Monday (3 calendar days).
"""
from __future__ import annotations

import argparse
import csv
import shutil
from datetime import date, datetime
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
CONFIG = HERE.parent / "config"

# Confirmed by Daniel Oct 28, 2026: Whs 10 is loaded Thursday and ships Friday; 3 days transit for all.
SCHEDULE = [
    {"ShipToKey": "WHS-22", "ShipToName": "Sub-Zero Whs 22 (Tue truck)", "TruckWeekday": 2, "TransitCalendarDays": 3, "DateBasis": "D", "LoadDaysBefore": 0, "Active": 1},
    {"ShipToKey": "WHS-23", "ShipToName": "Sub-Zero Whs 23 (Tue truck)", "TruckWeekday": 2, "TransitCalendarDays": 3, "DateBasis": "D", "LoadDaysBefore": 0, "Active": 1},
    {"ShipToKey": "WHS-10", "ShipToName": "Sub-Zero Whs 10 (loaded Thu, ships Fri)", "TruckWeekday": 5, "TransitCalendarDays": 3, "DateBasis": "D", "LoadDaysBefore": 1, "Active": 1},
]


def as_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str) and v.strip():
        try:
            return datetime.strptime(v.strip(), "%m/%d/%Y").date()
        except ValueError:
            return None
    return None


def ready_state(status: str | None) -> str:
    s = (status or "").strip().lower()
    if not s:
        return "Unknown"
    if "ready to ship" in s:
        return "Ready"
    if "raw material" in s:
        return "NoMaterial"
    return "NotReady"            # needs painted / stamp / rolled / assembled, to build


def find_header(ws) -> tuple[int, dict]:
    for row in ws.iter_rows(min_row=1, max_row=20):
        vals = [c.value for c in row]
        if vals and vals[0] == "Order" and "Item" in vals:
            return row[0].row, {str(v).strip(): i for i, v in enumerate(vals) if v is not None}
    raise SystemExit("Header row with 'Order' / 'Item' not found")


def read_syspro(path: Path | None) -> list[dict]:
    if not path:
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if r.get("LineStatus", "Open") not in ("Cancelled", "Complete")]


def main(xlsx: Path, out: Path, syspro: Path | None = None) -> None:
    wb = openpyxl.load_workbook(xlsx, data_only=True)      # uses the values Excel last calculated
    ws = next(w for w in wb.worksheets if w.title.lower().startswith("open purchase orders"))
    hdr_row, h = find_header(ws)
    col = lambda r, name: r[h[name]] if name in h and h[name] < len(r) else None

    reqs, ships = [], []
    erp = read_syspro(syspro)
    erp_by_key: dict[tuple, list[dict]] = {}
    for e in erp:
        erp_by_key.setdefault((e["CustomerPoNumber"].strip(), e["StockCode"].strip()), []).append(e)
    matched = set()
    for r in ws.iter_rows(min_row=hdr_row + 1, values_only=True):
        if not r or not r[0] or not str(r[0]).startswith("P"):
            continue
        order, line, rel = str(r[0]).strip(), col(r, "Line"), col(r, "Release")
        key = f"{order}|{line}|{rel}"
        cust_open = float(col(r, "Open Qty") or 0)
        shipped = float(col(r, "Qty Shipped") or 0)
        remaining = float(col(r, "Qty Remaining to Ship") if col(r, "Qty Remaining to Ship") is not None else cust_open - shipped)
        due = as_date(col(r, "Due Date (date)")) or as_date(col(r, "Due Date"))
        ship_status = col(r, "Ship Status") or ""
        prod = col(r, "Status")
        notes = " | ".join(str(x) for x in (col(r, "Your Ship Date"), prod, ship_status) if x)
        data_note = ""
        if "qty not stated" in ship_status.lower():
            data_note = "Partial shipment with qty not stated - plan credits the full qty; confirm"
        elif "error" in ship_status.lower():
            data_note = "Shipping error under investigation"
        match_status = ""
        if erp:                                           # Mills' open qty comes from SYSPRO, not the plan
            hits = erp_by_key.get((order, str(col(r, "Item")).strip()), [])
            if hits:
                matched.update(id(e) for e in hits)
                erp_open = sum(float(e["OpenQty"] or 0) for e in hits)
                shipped, remaining, match_status = max(0.0, cust_open - erp_open), erp_open, "Matched"
                if erp_open > cust_open:
                    data_note = (data_note + "; " if data_note else "") + \
                        f"SYSPRO open {erp_open:,.0f} > customer open {cust_open:,.0f}; update the SO"
            else:
                shipped, remaining, match_status = 0.0, cust_open, "NotInERP"
        reqs.append({
            "Customer": "SUBZERO", "CustomerGroup": "Sub-Zero/Wolf", "CustomerPoNumber": order,
            "SalesOrder": order, "SalesOrderLine": f"{line}.{rel}", "ReqKey": key,
            "StockCode": str(col(r, "Item")).strip(), "StockDescription": col(r, "Description"),
            "Warehouse": "", "ShipToKey": f"WHS-{str(col(r, 'Whs')).strip()}",
            "OrderQty": cust_open, "ShippedQty": shipped, "OpenQty": remaining, "CustomerOpenQty": cust_open,
            "OrderLineDate": due.isoformat() if due else "", "OrderDate": "", "UnitPrice": "",
            "OrderStatus": "", "LineStatus": "Open",
            "ReadyState": ready_state(prod) if remaining > 0 else "",
            "Notes": notes, "DataNote": data_note, "MatchStatus": match_status,
        })
        sd = as_date(col(r, "Ship Date to Subzero"))
        if shipped > 0 and sd:
            ships.append({"ShipmentNo": f"PLAN-{order}", "DetailLine": 1, "SalesOrder": order,
                          "SalesOrderLine": f"{line}.{rel}", "ReqKey": key, "StockCode": reqs[-1]["StockCode"],
                          "Customer": "SUBZERO", "ShipQty": shipped, "ShipDate": sd.isoformat()})

    out.mkdir(parents=True, exist_ok=True)

    def write(name, rows, fields=None):
        fields = fields or list(rows[0].keys())
        with (out / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    write("requirements.csv", reqs)
    write("shipments.csv", ships, ["ShipmentNo", "DetailLine", "SalesOrder", "SalesOrderLine", "ReqKey",
                                   "StockCode", "Customer", "ShipQty", "ShipDate"])
    write("shipto_schedule.csv", SCHEDULE)
    erp_only = [e for e in erp if id(e) not in matched and float(e["OpenQty"] or 0) > 0]
    write("erp_only_lines.csv", erp_only,
          list(erp[0].keys()) if erp else ["ReqKey", "StockCode", "Customer", "ShipToKey", "OrderLineDate", "OpenQty", "CustomerPoNumber"])
    (out / "fg_inventory.csv").write_text("StockCode,Warehouse,OnHandQty,AllocatedQty,InTransitQty,UnitCost,Description,ProductClass\n")
    shutil.copy(CONFIG / "SZW_Routing.csv", out / "SZW_Routing.csv")

    # Config + plant holidays from the plan's Backlog Projection sheet (D4:D9)
    holidays = []
    if "Backlog Projection" in wb.sheetnames:
        bp = wb["Backlog Projection"]
        holidays = [as_date(bp.cell(row=i, column=4).value) for i in range(4, 12)]
    holidays = [h.isoformat() for h in holidays if h]
    with (CONFIG / "SZW_Config.csv").open(encoding="utf-8") as f:
        cfg = list(csv.DictReader(f))
    if holidays:                                   # the plan's list wins; otherwise keep the config's
        cfg = [r for r in cfg if r["Key"] != "Holidays"]
        cfg.append({"Key": "Holidays", "Value": ";".join(holidays), "Description": "From the plan's holiday list"})
    else:
        holidays = next((r["Value"].split(";") for r in cfg if r["Key"] == "Holidays"), [])
    write("SZW_Config.csv", cfg, ["Key", "Value", "Description"])
    print(f"{len(reqs)} PO lines, {len(ships)} shipments, holidays {holidays} -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsx", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--syspro", type=Path, help="CSV of rpt.vw_SZW_Requirements; Mills open qty is taken from it")
    a = ap.parse_args()
    main(a.xlsx, a.out, a.syspro)
