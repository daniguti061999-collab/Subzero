"""Generate the PBIR report (3 pages) for the SZW Backlog Monitor PBIP."""
import json, pathlib, shutil, sys
ROOT = pathlib.Path(sys.argv[1]); LOGO = pathlib.Path(sys.argv[2]); THEME = pathlib.Path(sys.argv[3])
NAME = "SZW_Backlog_Monitor"
RPT = ROOT / f"{NAME}.Report"; DEF = RPT / "definition"
S = "https://developer.microsoft.com/json-schemas/fabric/"
VC = S + "item/report/definition/visualContainer/2.4.0/schema.json"
NAVY, BLUE, RED, AMBER, GREEN, GREY, PAGE, FOOT = "#002F6C", "#1D4E89", "#C0392B", "#B9770E", "#1E8449", "#4B5563", "#F4F6F9", "#DBE2E9"

def w(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

def lit(v): return {"expr": {"Literal": {"Value": v}}}
def s_(t): return lit("'" + t.replace("'", "''") + "'")
def num(n): return lit(f"{n}D")
def b(v): return lit("true" if v else "false")
def col(c): return {"solid": {"color": s_(c)}}
def M(p, e="Requirements"): return {"Measure": {"Expression": {"SourceRef": {"Entity": e}}, "Property": p}}
def C(p, e="Requirements"): return {"Column": {"Expression": {"SourceRef": {"Entity": e}}, "Property": p}}
def proj(f, name=None):
    k = "Measure" if "Measure" in f else "Column"
    e, p = f[k]["Expression"]["SourceRef"]["Entity"], f[k]["Property"]
    out = {"field": f, "queryRef": f"{e}.{p}", "nativeQueryRef": p}
    if name: out["displayName"] = name
    return out
def mexpr(p, e="Requirements"): return {"expr": M(p, e)}

def container(title=None, title_measure=None, sub_measure=None, bg=True, bg_color="#FFFFFF", border=True, fcolor=NAVY, tsize=11, header=False):
    o = {"background": [{"properties": {"show": b(bg), "color": col(bg_color), "transparency": num(0)}}],
         "border": [{"properties": {"show": b(border), "color": col("#E5E7EB"), "radius": num(8)}}],
         "dropShadow": [{"properties": {"show": b(False)}}],
         "visualHeader": [{"properties": {"show": b(header)}}]}
    if title or title_measure:
        tp = {"show": b(True), "fontColor": col(fcolor), "fontSize": num(tsize), "bold": b(True)}
        tp["text"] = mexpr(title_measure) if title_measure else s_(title)
        o["title"] = [{"properties": tp}]
    else:
        o["title"] = [{"properties": {"show": b(False)}}]
    if sub_measure:
        o["subTitle"] = [{"properties": {"show": b(True), "text": mexpr(sub_measure), "fontColor": col(GREY), "fontSize": num(9)}}]
    return o

class Page:
    def __init__(self, name, display):
        self.name, self.display, self.visuals, self.z = name, display, [], 0
    def add(self, vname, x, y, wd, h, visual, filters=None):
        self.z += 1000
        v = {"$schema": VC, "name": vname, "position": {"x": x, "y": y, "z": self.z, "width": wd, "height": h, "tabOrder": self.z},
             "visual": visual}
        if filters: v["filterConfig"] = {"filters": filters}
        self.visuals.append(v)
    def write(self):
        base = DEF / "pages" / self.name
        w(base / "page.json", {"$schema": S + "item/report/definition/page/2.0.0/schema.json", "name": self.name,
            "displayName": self.display, "displayOption": "FitToPage", "height": 720, "width": 1280,
            "objects": {"background": [{"properties": {"color": col(PAGE), "transparency": num(0)}}],
                        "outspace": [{"properties": {"color": col(PAGE)}}]}})
        for v in self.visuals:
            w(base / "visuals" / v["name"] / "visual.json", v)

def shape(fill):
    return {"visualType": "shape",
            "objects": {"shape": [{"properties": {"tileShape": s_("rectangle")}}],
                        "fill": [{"properties": {"show": b(True), "fillColor": col(fill), "transparency": num(0)}}],
                        "outline": [{"properties": {"show": b(False)}}]},
            "visualContainerObjects": {"background": [{"properties": {"show": b(False)}}], "title": [{"properties": {"show": b(False)}}],
                                       "visualHeader": [{"properties": {"show": b(False)}}]}}

def text_card(measure, size, color, bold=False):
    return {"visualType": "card",
            "query": {"queryState": {"Values": {"projections": [proj(M(measure))]}}},
            "objects": {"labels": [{"properties": {"color": col(color), "fontSize": num(size), "bold": b(bold)}}],
                        "categoryLabels": [{"properties": {"show": b(False)}}]},
            "visualContainerObjects": container(bg=False, border=False)}

def kpi(value, title_m, sub_m, color):
    return {"visualType": "card",
            "query": {"queryState": {"Values": {"projections": [proj(M(value))]}}},
            "objects": {"labels": [{"properties": {"color": col(color), "fontSize": num(26)}}],
                        "categoryLabels": [{"properties": {"show": b(False)}}]},
            "visualContainerObjects": container(title_measure=title_m, sub_measure=sub_m, fcolor=GREY, tsize=10)}

def slicer(field, title_m, mode="Dropdown", horizontal=False, single=False, white_title=True):
    o = {"data": [{"properties": {"mode": s_(mode)}}], "header": [{"properties": {"show": b(False)}}]}
    if horizontal:
        o["general"] = [{"properties": {"orientation": num(1)}}]
    if single:
        o["selection"] = [{"properties": {"singleSelect": b(True), "strictSingleSelect": b(True)}}]
    if mode == "Basic":
        o["items"] = [{"properties": {"fontColor": col("#FFFFFF"), "background": col(BLUE), "textSize": num(10)}}]
    vc = container(title_measure=title_m, bg=False, border=False, fcolor="#FFFFFF" if white_title else NAVY, tsize=9) if title_m else container(bg=False, border=False)
    return {"visualType": "slicer", "query": {"queryState": {"Values": {"projections": [proj(field)]}}}, "objects": o,
            "visualContainerObjects": vc, "drillFilterOtherVisuals": True}

def table(fields, title_m=None, sort=None, font=9):
    v = {"visualType": "tableEx", "query": {"queryState": {"Values": {"projections": [proj(f, n) for f, n in fields]}}},
         "objects": {"columnHeaders": [{"properties": {"fontColor": col("#FFFFFF"), "backColor": col(NAVY), "fontSize": num(font)}}],
                     "values": [{"properties": {"fontSize": num(font)}}],
                     "grid": [{"properties": {"gridHorizontal": b(True), "gridVertical": b(False)}}]},
         "visualContainerObjects": container(title_measure=title_m), "drillFilterOtherVisuals": True}
    if sort:
        v["query"]["sortDefinition"] = {"sort": [{"field": f, "direction": d} for f, d in sort], "isDefaultSort": False}
    return v

def in_filter(name, entity, prop, values, boolean=False):
    vals = [[{"Literal": {"Value": ("true" if v else "false") if boolean else "'" + v.replace("'", "''") + "'"}}] for v in values]
    return {"name": name, "field": C(prop, entity), "type": "Categorical",
            "filter": {"Version": 2, "From": [{"Name": "f", "Entity": entity, "Type": 0}],
                       "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": prop}}],
                                                       "Values": vals}}}]}}

def header(p, title_m="T Title", show_sub=True):
    p.add("hdrBand", 0, 0, 1280, 70, shape(NAVY))
    p.add("hdrLogo", 14, 14, 230, 42, {"visualType": "image",
        "objects": {"general": [{"properties": {"imageUrl": {"expr": {"ResourcePackageItem": {"PackageName": "RegisteredResources", "PackageType": 1, "ItemName": "MillsLogo.png"}}}}}],
                    "imageScaling": [{"properties": {"imageScalingType": s_("Fit")}}]},
        "visualContainerObjects": {"background": [{"properties": {"show": b(False)}}], "title": [{"properties": {"show": b(False)}}],
                                   "visualHeader": [{"properties": {"show": b(False)}}]}})
    p.add("hdrTitle", 270, 2, 560, 36, text_card(title_m, 18, "#FFFFFF", True))
    if show_sub:
        p.add("hdrAsOf", 270, 40, 560, 28, text_card("T As Of", 10, "#DCE6F2"))
    p.add("slShipTo", 850, 4, 112, 62, slicer(C("ShipToName", "ShipToSchedule"), "T ShipTo"))
    p.add("slPart", 968, 4, 100, 62, slicer(C("StockCode", "Parts"), "T Part"))
    p.add("slStatus", 1074, 4, 100, 62, slicer(C("Status"), "T Status"))
    p.add("slLang", 1182, 14, 90, 44, slicer(C("Code", "Language"), None, mode="Basic", horizontal=True, single=True))

def footer(p, text):
    p.add("ftBand", 0, 696, 1280, 24, shape("#DBE2E9"))
    p.add("ftText", 8, 696, 1264, 24, {"visualType": "textbox",
        "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [{"value": text, "textStyle": {"fontSize": "8pt", "color": "#12239E"}}]}]}}]},
        "visualContainerObjects": {"background": [{"properties": {"show": b(False)}}], "title": [{"properties": {"show": b(False)}}],
                                   "visualHeader": [{"properties": {"show": b(False)}}]}})

# ---------------- Page 1: Monitor ----------------
p1 = Page("monitor", "Monitor")
header(p1)
kpis = [("Past Due Qty", "T Past Due", "KPI Sub Past Due", RED), ("True Backlog Qty", "T True Backlog", "KPI Sub True Backlog", RED),
        ("Critical Short Qty", "T Critical", "KPI Sub Critical", RED), ("At Risk Short Qty", "T At Risk", "KPI Sub At Risk", AMBER),
        ("Shipped Not Credited Qty", "T Not Credited", "KPI Sub Not Credited", BLUE)]
for i, (v, t, sub, c) in enumerate(kpis):
    p1.add(f"kpi{i+1}", 12 + i * 253, 80, 241, 96, kpi(v, t, sub, c))
p1.add("tblTrucks", 12, 186, 400, 236, table([(C("ReqShipDate"), "Truck date"), (C("Truck"), "Truck"), (C("ShipToName", "ShipToSchedule"), "Ship-to"),
        (M("Lines"), "Lines"), (M("Open Qty"), "Open"), (M("Short Qty"), "Short")], "T Next Trucks",
        sort=[(C("ReqShipDate"), "Ascending")]),
        filters=[in_filter("fTruckWindow", "Requirements", "TruckWindow", ["Next truck", "Truck after"])])
p1.add("barAging", 420, 186, 440, 236, {"visualType": "barChart",
        "query": {"queryState": {"Category": {"projections": [proj(C("StockCode"))]},
                                 "Series": {"projections": [proj(C("AgingBucket"))]},
                                 "Y": {"projections": [proj(M("Past Due Qty"))]}},
                  "sortDefinition": {"sort": [{"field": M("Past Due Qty"), "direction": "Descending"}], "isDefaultSort": False}},
        "objects": {"legend": [{"properties": {"show": b(True), "position": s_("Top")}}],
                    "labels": [{"properties": {"show": b(False)}}]},
        "visualContainerObjects": container(title_measure="T Aging"), "drillFilterOtherVisuals": True},
        filters=[in_filter("fPastDue", "Requirements", "Status", ["Past Due"])])
p1.add("lineTrend", 868, 186, 400, 236, {"visualType": "lineChart",
        "query": {"queryState": {"Category": {"projections": [proj(C("SnapshotDate", "BacklogSnapshot"))]},
                                 "Y": {"projections": [proj(M("Snapshot Past Due Qty"))]}}},
        "objects": {"dataPoint": [{"properties": {"fill": col(NAVY)}}], "labels": [{"properties": {"show": b(True)}}]},
        "visualContainerObjects": container(title_measure="T Trend"), "drillFilterOtherVisuals": True})
p1.add("tblExceptions", 12, 430, 1256, 258, table([(C("Severity", "Exceptions"), "Severity"), (C("RuleID", "Exceptions"), "Rule"),
        (C("RuleDescription", "Exceptions"), "What"), (C("Part", "Exceptions"), "Part"), (C("ReqKey", "Exceptions"), "PO line"),
        (C("ReqShipDate", "Exceptions"), "Truck date"), (C("OpenQty", "Exceptions"), "Qty"), (C("ShortQty", "Exceptions"), "Short"),
        (C("DaysPastDue", "Exceptions"), "Days"), (C("Owners", "Exceptions"), "Owner"), (C("Status", "Exceptions"), "Status"),
        (C("Detail", "Exceptions"), "Detail")], "T Exceptions",
        sort=[(C("DaysPastDue", "Exceptions"), "Descending")]),
        filters=[in_filter("fOpen", "Exceptions", "IsOpen", [True], boolean=True)])
footer(p1, "Demand: Sub-Zero Open PO list. Mills shipments and production notes: Oct 28 recovery plan (SYSPRO in production). "
           "Trucks: Whs 22/23 Tue, arrive Fri; Whs 10 loaded Thu, ships Fri, arrives Mon. Past due = missed its truck.")

# ---------------- Page 2: Lines ----------------
p2 = Page("lines", "PO lines")
header(p2, "T Lines", show_sub=True)
p2.add("tblLines", 12, 80, 1256, 608, table([(C("Status"), "Status"), (C("ShipToName", "ShipToSchedule"), "Ship-to"), (C("StockCode"), "Part"),
        (C("StockDescription"), "Description"), (C("ReqKey"), "PO line"), (C("OrderLineDate"), "Sub-Zero due"), (C("ReqShipDate"), "Truck date"),
        (C("Truck"), "Truck"), (C("ReadyBy"), "Ready by"), (C("CustomerOpenQty"), "Sub-Zero open"), (C("OpenQty"), "Mills open"),
        (C("ShortQty"), "Short"), (C("DaysPastDue"), "Days late"), (C("ShippedNotCreditedQty"), "Shipped, not credited"),
        (C("ReadyState"), "Readiness"), (C("Notes"), "Plan notes")], None,
        sort=[(C("Status"), "Ascending"), (C("DaysPastDue"), "Descending")], font=8))
footer(p2, "One row per Sub-Zero PO line. Readiness comes from the production note until SYSPRO FG stock is connected.")

# ---------------- Page 3: Data health ----------------
p3 = Page("health", "Data health")
header(p3, "T Health", show_sub=True)
p3.add("kpiMismatch", 12, 80, 300, 96, kpi("Mismatch Lines", "T Health", None, RED))
p3.add("kpiUnknown", 324, 80, 300, 96, {"visualType": "card", "query": {"queryState": {"Values": {"projections": [proj(M("Readiness Unknown Lines"), "Lines with no production note")]}}},
        "objects": {"labels": [{"properties": {"color": col(AMBER), "fontSize": num(26)}}]},
        "visualContainerObjects": container(title="Open lines with no production note (treated as ready)", fcolor=GREY, tsize=10)})
p3.add("kpiRaw", 636, 80, 300, 96, {"visualType": "card", "query": {"queryState": {"Values": {"projections": [proj(M("Raw Material Risk Qty"), "Raw material risk")]}}},
        "objects": {"labels": [{"properties": {"color": col(AMBER), "fontSize": num(26)}}]},
        "visualContainerObjects": container(title="Raw material missing inside the 8-week lead time (pcs)", fcolor=GREY, tsize=10)})
p3.add("tblCompare", 12, 186, 760, 250, table([(C("Status"), "Status"), (M("Lines"), "Model lines"), (M("Engine Lines"), "Engine lines"),
        (M("Open Qty"), "Model open"), (M("Engine Open Qty"), "Engine open"), (M("Short Qty"), "Model short"), (M("Engine Short Qty"), "Engine short")],
        None, sort=[(C("Status"), "Ascending")]))
p3.add("tblMismatch", 12, 446, 1256, 242, table([(C("ReqKey"), "PO line"), (C("StockCode"), "Part"), (C("Status"), "Model status"),
        (C("EngineStatus"), "Engine status"), (C("ShortQty"), "Model short"), (C("EngineShortQty"), "Engine short")], None),
        filters=[in_filter("fMismatch", "Requirements", "MatchesEngine", [False], boolean=True)])
footer(p3, "The model must give the same status and short qty as engine/szw_agent.py for every line. Mismatch lines should be 0.")

for p in (p1, p2, p3):
    p.write()

# ---------------- report-level files ----------------
w(DEF / "version.json", {"$schema": S + "item/report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
w(DEF / "pages" / "pages.json", {"$schema": S + "item/report/definition/pagesMetadata/1.0.0/schema.json",
                                 "pageOrder": ["monitor", "lines", "health"], "activePageName": "monitor"})
w(DEF / "report.json", {"$schema": S + "item/report/definition/report/3.0.0/schema.json",
    "themeCollection": {"customTheme": {"name": "MillsTheme.json", "reportVersionAtImport": {"visual": "2.4.0", "report": "3.0.0", "page": "2.0.0"},
                                        "type": "RegisteredResources"}},
    "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources",
                          "items": [{"name": "MillsTheme.json", "path": "MillsTheme.json", "type": "CustomTheme"},
                                    {"name": "MillsLogo.png", "path": "MillsLogo.png", "type": "Image"}]}]})
w(RPT / "definition.pbir", {"$schema": S + "item/report/definitionProperties/2.0.0/schema.json", "version": "4.0",
                            "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})
res = RPT / "StaticResources" / "RegisteredResources"; res.mkdir(parents=True, exist_ok=True)
shutil.copy(LOGO, res / "MillsLogo.png"); shutil.copy(THEME, res / "MillsTheme.json")
w(ROOT / f"{NAME}.SemanticModel" / "definition.pbism", {"$schema": S + "item/semanticModel/definitionProperties/1.0.0/schema.json",
                                                        "version": "4.0", "settings": {}})
w(ROOT / f"{NAME}.pbip", {"$schema": S + "pbip/pbipProperties/1.0.0/schema.json", "version": "1.0",
                          "artifacts": [{"report": {"path": f"{NAME}.Report"}}], "settings": {"enableAutoRecovery": True}})
print("report written:", sum(len(p.visuals) for p in (p1, p2, p3)), "visuals")
