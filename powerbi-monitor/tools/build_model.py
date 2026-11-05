"""Generate the TMDL semantic model for the SZW Backlog Monitor PBIP."""
import pathlib, textwrap, sys
ROOT = pathlib.Path(sys.argv[1])
SM = ROOT / "SZW_Backlog_Monitor.SemanticModel"
DEF = SM / "definition"
(DEF / "tables").mkdir(parents=True, exist_ok=True)
T = "\t"

def block(text, level):
    """Indent a multi-line expression by `level` tabs (no blank lines allowed)."""
    lines = [l for l in textwrap.dedent(text).strip("\n").split("\n") if l.strip()]
    return "\n".join(T * level + l for l in lines)

def col(name, dtype, src=None, fmt=None, summarize="none", hidden=False, calc=None, inferred=False, folder=None, sortby=None):
    q = f"'{name}'" if any(c in name for c in " %/-().") else name
    out = []
    if calc:
        out.append(f"{T}column {q} =\n{block(calc, 3)}")
    else:
        out.append(f"{T}column {q}")
    out.append(f"{T*2}dataType: {dtype}")
    if fmt: out.append(f"{T*2}formatString: {fmt}")
    if hidden: out.append(f"{T*2}isHidden")
    if folder: out.append(f"{T*2}displayFolder: {folder}")
    out.append(f"{T*2}summarizeBy: {summarize}")
    if inferred: out.append(f"{T*2}isNameInferred")
    if src: out.append(f"{T*2}sourceColumn: {src}")
    if sortby: out.append(f"{T*2}sortByColumn: {sortby}")
    return "\n".join(out) + "\n"

def measure(name, expr, fmt=None, folder=None):
    q = f"'{name}'"
    out = [f"{T}measure {q} =\n{block(expr, 3)}"]
    if fmt: out.append(f"{T*2}formatString: {fmt}")
    if folder: out.append(f"{T*2}displayFolder: {folder}")
    return "\n".join(out) + "\n"

def mpart(table, m):
    return f"{T}partition {table} = m\n{T*2}mode: import\n{T*2}source =\n{block(m, 4)}\n"

def cpart(table, dax):
    return f"{T}partition {table} = calculated\n{T*2}mode: import\n{T*2}source =\n{block(dax, 4)}\n"

def table(name, parts):
    q = f"'{name}'" if " " in name else name
    (DEF / "tables" / f"{name}.tmdl").write_text(f"table {q}\n\n" + "\n".join(parts), encoding="utf-8")

def csv_m(rel, cols, types, blanks=None, extra=""):
    collist = ", ".join(f'"{c}"' for c in cols)
    typ = ", ".join(f'{{"{c}", {t}}}' for c, t in types)
    bl = ", ".join(f'"{c}"' for c in (blanks or [c for c, _ in types]))
    return f'''
    let
        Source = Csv.Document(File.Contents(DataFolder & "{rel}"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
        Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
        Cols = Table.SelectColumns(Promoted, {{{collist}}}, MissingField.UseNull),
        Blanks = Table.ReplaceValue(Cols, "", null, Replacer.ReplaceValue, {{{bl}}}),
        Typed = Table.TransformColumnTypes(Blanks, {{{typ}}}, "en-US"){extra}
    in
        Result
    '''

# ------------------------------------------------------------------ Requirements
req_text = ["Customer", "CustomerGroup", "CustomerPoNumber", "SalesOrder", "SalesOrderLine", "ReqKey", "StockCode",
            "StockDescription", "ShipToKey", "LineStatus", "ReadyState", "Notes", "DataNote", "MatchStatus"]
req_num = ["OrderQty", "ShippedQty", "OpenQty", "CustomerOpenQty", "UnitPrice"]
req_m = csv_m(r"input\requirements.csv", req_text + req_num + ["OrderLineDate"],
              [(c, "type number") for c in req_num] + [("OrderLineDate", "type date")],
              blanks=req_num + ["OrderLineDate", "ReadyState", "MatchStatus", "DataNote"],
              extra=''',
        Result = Table.SelectRows(Typed, each [LineStatus] <> "Cancelled")''')

ASOF = "MAX ( RunInfo[AsOfDate] )"
calc = {}
calc["ReqShipDate"] = f'''
    // Truck departure that meets the Sub-Zero due date (arrival), moved to the business day before a holiday
    VAR lineDate = Requirements[OrderLineDate]
    VAR wd = RELATED ( ShipToSchedule[TruckWeekday] )
    VAR transit = RELATED ( ShipToSchedule[TransitCalendarDays] )
    VAR basis = RELATED ( ShipToSchedule[DateBasis] )
    VAR latest = IF ( basis = "D", lineDate - transit, lineDate )
    VAR truck = latest - MOD ( WEEKDAY ( latest, 2 ) - wd, 7 )
    RETURN
        IF ( ISBLANK ( lineDate ), BLANK (),
            IF ( ISBLANK ( wd ), lineDate,
                MAXX ( FILTER ( BizCalendar, BizCalendar[Date] <= truck && BizCalendar[IsBusinessDay] ), BizCalendar[Date] ) ) )
'''
calc["Truck"] = '''
    VAR wd = RELATED ( ShipToSchedule[TruckWeekday] )
    RETURN IF ( ISBLANK ( wd ), BLANK (), FORMAT ( DATE ( 2024, 1, wd ), "ddd" ) & " truck" )
'''
calc["ReadyBy"] = '''
    VAR ld = RELATED ( ShipToSchedule[LoadDaysBefore] )
    VAR s = Requirements[ReqShipDate]
    RETURN
        IF ( ISBLANK ( s ), BLANK (),
            IF ( ld > 0, MAXX ( FILTER ( BizCalendar, BizCalendar[Date] <= s - ld && BizCalendar[IsBusinessDay] ), BizCalendar[Date] ), s ) )
'''
calc["NextTruck1"] = f'''
    VAR asof = {ASOF}
    VAR wd = RELATED ( ShipToSchedule[TruckWeekday] )
    RETURN IF ( ISBLANK ( wd ), asof + 1, asof + MOD ( wd - WEEKDAY ( asof, 2 ), 7 ) )
'''
calc["NextTruck2"] = f'''
    VAR wd = RELATED ( ShipToSchedule[TruckWeekday] )
    RETURN IF ( ISBLANK ( wd ), {ASOF} + 7, Requirements[NextTruck1] + 7 )
'''
calc["HasFG"] = '''
    VAR p = Requirements[StockCode]
    RETURN COUNTROWS ( FILTER ( FGInventory, FGInventory[StockCode] = p && NOT ( FGInventory[Warehouse] IN { "QH" } ) ) ) > 0
'''
calc["FGAvailable"] = '''
    // FG on hand outside quality-hold warehouses (QH - VERIFY code)
    VAR p = Requirements[StockCode]
    RETURN SUMX ( FILTER ( FGInventory, FGInventory[StockCode] = p && NOT ( FGInventory[Warehouse] IN { "QH" } ) ), FGInventory[OnHandQty] ) + 0
'''
calc["CumOpenByPart"] = '''
    VAR p = Requirements[StockCode]
    VAR d = COALESCE ( Requirements[ReqShipDate], DATE ( 9999, 12, 31 ) )
    VAR k = Requirements[ReqKey]
    RETURN
        SUMX (
            FILTER ( ALL ( Requirements[StockCode], Requirements[ReqShipDate], Requirements[ReqKey], Requirements[OpenQty] ),
                Requirements[StockCode] = p
                    && ( COALESCE ( Requirements[ReqShipDate], DATE ( 9999, 12, 31 ) ) < d
                         || ( COALESCE ( Requirements[ReqShipDate], DATE ( 9999, 12, 31 ) ) = d && Requirements[ReqKey] <= k ) ) ),
            Requirements[OpenQty] )
'''
calc["ShortQty"] = '''
    // FG netting when SYSPRO stock exists for the part; otherwise readiness from the production note
    VAR netted = MIN ( Requirements[OpenQty], MAX ( 0, Requirements[CumOpenByPart] - Requirements[FGAvailable] ) )
    RETURN
        IF ( NOT Requirements[HasFG] && Requirements[ReadyState] <> "",
            IF ( Requirements[ReadyState] IN { "Ready", "Unknown" }, 0, Requirements[OpenQty] ),
            netted )
'''
calc["DaysPastDue"] = f'''
    VAR asof = {ASOF}
    VAR s = Requirements[ReqShipDate]
    RETURN IF ( Requirements[OpenQty] > 0 && NOT ISBLANK ( s ) && s < asof, INT ( asof - s ), 0 )
'''
calc["AgingBucket"] = '''
    SWITCH ( TRUE (),
        Requirements[DaysPastDue] = 0, "Not past due",
        Requirements[DaysPastDue] <= 2, "1-2 days",
        Requirements[DaysPastDue] <= 7, "3-7 days",
        Requirements[DaysPastDue] <= 14, "8-14 days",
        "15+ days" )
'''
calc["AgingOrder"] = '''
    // Replicates AgingBucket logic to avoid sortByColumn circular dependency
    SWITCH ( TRUE (),
        Requirements[DaysPastDue] = 0, 0,
        Requirements[DaysPastDue] <= 2, 1,
        Requirements[DaysPastDue] <= 7, 2,
        Requirements[DaysPastDue] <= 14, 3,
        4 )
'''
calc["Status"] = f'''
    VAR asof = {ASOF}
    VAR s = Requirements[ReqShipDate]
    RETURN
        SWITCH ( TRUE (),
            Requirements[OpenQty] <= 0, "Complete",
            ISBLANK ( s ), "Data Issue",
            s < asof, "Past Due",
            Requirements[ShortQty] > 0 && s <= Requirements[NextTruck1], "Critical",
            Requirements[ShortQty] > 0 && s <= Requirements[NextTruck2], "At Risk",
            "On Track" )
'''
calc["StatusOrder"] = f'''
    // Replicates Status logic to avoid sortByColumn circular dependency
    VAR asof = {ASOF}
    VAR s = Requirements[ReqShipDate]
    RETURN
        SWITCH ( TRUE (),
            Requirements[OpenQty] <= 0, 6,
            ISBLANK ( s ), 4,
            s < asof, 1,
            Requirements[ShortQty] > 0 && s <= Requirements[NextTruck1], 2,
            Requirements[ShortQty] > 0 && s <= Requirements[NextTruck2], 3,
            5 )
'''
calc["TruckWindow"] = f'''
    VAR asof = {ASOF}
    VAR s = Requirements[ReqShipDate]
    RETURN
        SWITCH ( TRUE (),
            Requirements[OpenQty] <= 0, "Done",
            ISBLANK ( s ), "No date",
            s < asof, "Missed",
            s <= Requirements[NextTruck1], "Next truck",
            s <= Requirements[NextTruck2], "Truck after",
            "Later" )
'''
calc["LastShipDate"] = '''
    VAR k = Requirements[ReqKey]
    RETURN MAXX ( FILTER ( Shipments, Shipments[ReqKey] = k ), Shipments[ShipDate] )
'''
calc["ShippedNotCreditedQty"] = '''
    MAX ( 0, Requirements[CustomerOpenQty] - Requirements[OpenQty] )
'''
calc["C1Flag"] = f'''
    // Shipped by Mills, still open on Sub-Zero's list 1+ day after the truck should have arrived
    VAR asof = {ASOF}
    VAR basis = COALESCE ( Requirements[LastShipDate], Requirements[ReqShipDate] )
    VAR transit = COALESCE ( RELATED ( ShipToSchedule[TransitCalendarDays] ), 3 )
    VAR fromDay = MIN ( basis, asof ) + transit
    VAR arrival = MINX ( FILTER ( BizCalendar, BizCalendar[Date] >= fromDay && BizCalendar[IsBusinessDay] ), BizCalendar[Date] )
    RETURN Requirements[ShippedNotCreditedQty] > 0 && NOT ISBLANK ( basis ) && INT ( asof - arrival ) >= 1
'''
calc["PastDueBySubZero"] = f'''
    VAR asof = {ASOF}
    RETURN NOT ISBLANK ( Requirements[OrderLineDate] ) && Requirements[OrderLineDate] < asof
'''
calc["BizDaysToShip"] = f'''
    VAR asof = {ASOF}
    VAR s = Requirements[ReqShipDate]
    RETURN COUNTROWS ( FILTER ( BizCalendar, BizCalendar[Date] > asof && BizCalendar[Date] <= s && BizCalendar[IsBusinessDay] ) ) + 0
'''
calc["R8Flag"] = '''
    // Raw material missing and the truck is inside the 8-week (40 workday) lead time
    Requirements[ReadyState] = "NoMaterial"
        && Requirements[Status] IN { "On Track", "At Risk" }
        && Requirements[BizDaysToShip] <= 40
'''
calc["EngineStatus"] = '''
    VAR k = Requirements[ReqKey]
    RETURN MAXX ( FILTER ( EngineCheck, EngineCheck[ReqKey] = k ), EngineCheck[Status] )
'''
calc["EngineShortQty"] = '''
    VAR k = Requirements[ReqKey]
    RETURN MAXX ( FILTER ( EngineCheck, EngineCheck[ReqKey] = k ), EngineCheck[ShortQty] )
'''
calc["MatchesEngine"] = '''
    Requirements[Status] = Requirements[EngineStatus]
        && ABS ( Requirements[ShortQty] - Requirements[EngineShortQty] ) < 0.001
'''

types = {"ReqShipDate": ("dateTime", "yyyy-mm-dd"), "Truck": ("string", None), "ReadyBy": ("dateTime", "yyyy-mm-dd"),
         "NextTruck1": ("dateTime", "yyyy-mm-dd"), "NextTruck2": ("dateTime", "yyyy-mm-dd"), "HasFG": ("boolean", None),
         "FGAvailable": ("double", "#,0"), "CumOpenByPart": ("double", "#,0"), "ShortQty": ("double", "#,0"),
         "DaysPastDue": ("int64", "0"), "AgingBucket": ("string", None), "AgingOrder": ("int64", "0"),
         "Status": ("string", None), "StatusOrder": ("int64", "0"), "TruckWindow": ("string", None),
         "LastShipDate": ("dateTime", "yyyy-mm-dd"), "ShippedNotCreditedQty": ("double", "#,0"), "C1Flag": ("boolean", None),
         "PastDueBySubZero": ("boolean", None), "BizDaysToShip": ("int64", "0"), "R8Flag": ("boolean", None),
         "EngineStatus": ("string", None), "EngineShortQty": ("double", "#,0"), "MatchesEngine": ("boolean", None)}
hidden_calc = {"NextTruck1", "NextTruck2", "HasFG", "CumOpenByPart", "AgingOrder", "StatusOrder", "BizDaysToShip", "EngineShortQty"}

parts = []
for c in req_text:
    parts.append(col(c, "string", src=c, folder="Source"))
for c in req_num:
    parts.append(col(c, "double", src=c, fmt="#,0", summarize="sum", folder="Source"))
parts.append(col("OrderLineDate", "dateTime", src="OrderLineDate", fmt="yyyy-mm-dd", folder="Source"))
for name, expr in calc.items():
    dt, fmt = types[name]
    sort = {"Status": "StatusOrder", "AgingBucket": "AgingOrder"}.get(name)
    parts.append(col(name, dt, fmt=fmt, calc=expr, hidden=name in hidden_calc, folder="Agent", sortby=sort,
                     summarize="sum" if name in ("ShortQty", "ShippedNotCreditedQty", "FGAvailable") else "none"))

M = []  # measures on Requirements
def ms(name, expr, fmt="#,0", folder="KPI"):
    M.append(measure(name, expr, fmt, folder))
ms("As Of Date", ASOF, "ddd mmm d, yyyy", "Info")
ms("Open Qty", "SUM ( Requirements[OpenQty] )")
ms("Lines", "COUNTROWS ( Requirements )", "#,0")
ms("Short Qty", "SUM ( Requirements[ShortQty] )")
ms("Past Due Qty", 'CALCULATE ( SUM ( Requirements[OpenQty] ), Requirements[Status] = "Past Due" ) + 0')
ms("Past Due Lines", 'CALCULATE ( COUNTROWS ( Requirements ), Requirements[Status] = "Past Due" ) + 0')
ms("Past Due $", 'SUMX ( FILTER ( Requirements, Requirements[Status] = "Past Due" ), Requirements[OpenQty] * Requirements[UnitPrice] )', "$#,0")
ms("SZ Open Qty", "SUM ( Requirements[CustomerOpenQty] )")
ms("SZ Past Due Qty", "CALCULATE ( SUM ( Requirements[CustomerOpenQty] ), Requirements[PastDueBySubZero] = TRUE () ) + 0")
ms("True Backlog Qty", "CALCULATE ( SUM ( Requirements[OpenQty] ), Requirements[PastDueBySubZero] = TRUE () ) + 0")
ms("Missed Truck Not Yet Due Qty", 'CALCULATE ( SUM ( Requirements[OpenQty] ), Requirements[Status] = "Past Due", Requirements[PastDueBySubZero] = FALSE () ) + 0')
ms("Critical Short Qty", 'CALCULATE ( SUM ( Requirements[ShortQty] ), Requirements[Status] = "Critical" ) + 0')
ms("Critical Lines", 'CALCULATE ( COUNTROWS ( Requirements ), Requirements[Status] = "Critical" ) + 0')
ms("At Risk Short Qty", 'CALCULATE ( SUM ( Requirements[ShortQty] ), Requirements[Status] = "At Risk" ) + 0')
ms("At Risk Lines", 'CALCULATE ( COUNTROWS ( Requirements ), Requirements[Status] = "At Risk" ) + 0')
ms("Shipped Not Credited Qty", "SUM ( Requirements[ShippedNotCreditedQty] ) + 0")
ms("C1 Lines", "CALCULATE ( COUNTROWS ( Requirements ), Requirements[C1Flag] = TRUE () ) + 0")
ms("Raw Material Risk Qty", "CALCULATE ( SUM ( Requirements[OpenQty] ), Requirements[R8Flag] = TRUE () ) + 0")
ms("Readiness Unknown Lines", 'CALCULATE ( COUNTROWS ( Requirements ), Requirements[ReadyState] = "Unknown", Requirements[OpenQty] > 0 ) + 0')
ms("Next 12 Weeks Qty", f"VAR d = {ASOF} RETURN CALCULATE ( SUM ( Requirements[OpenQty] ), Requirements[ReqShipDate] >= d, Requirements[ReqShipDate] <= d + 84 ) + 0")
ms("Snapshot Past Due Qty", "SUM ( BacklogSnapshot[PastDueQty] )", "#,0", "Trend")
ms("Past Due Prior Snapshot", f'''
    VAR asof = {ASOF}
    VAR prev = CALCULATE ( MAX ( BacklogSnapshot[SnapshotDate] ), REMOVEFILTERS ( BacklogSnapshot ), BacklogSnapshot[SnapshotDate] < asof )
    RETURN CALCULATE ( SUM ( BacklogSnapshot[PastDueQty] ), REMOVEFILTERS ( BacklogSnapshot ), BacklogSnapshot[SnapshotDate] = prev )
''', "#,0", "Trend")
ms("Past Due Change %", "DIVIDE ( [Past Due Qty] - [Past Due Prior Snapshot], [Past Due Prior Snapshot] )", "+0.0%;-0.0%;0.0%", "Trend")
ms("Engine Lines", "VAR s = SELECTEDVALUE ( Requirements[Status] ) RETURN COUNTROWS ( FILTER ( ALL ( EngineCheck ), EngineCheck[Status] = s ) ) + 0", "#,0", "Data health")
ms("Engine Open Qty", "VAR s = SELECTEDVALUE ( Requirements[Status] ) RETURN SUMX ( FILTER ( ALL ( EngineCheck ), EngineCheck[Status] = s ), EngineCheck[OpenQty] ) + 0", "#,0", "Data health")
ms("Engine Short Qty", "VAR s = SELECTEDVALUE ( Requirements[Status] ) RETURN SUMX ( FILTER ( ALL ( EngineCheck ), EngineCheck[Status] = s ), EngineCheck[ShortQty] ) + 0", "#,0", "Data health")
ms("Mismatch Lines", "CALCULATE ( COUNTROWS ( Requirements ), Requirements[MatchesEngine] = FALSE () ) + 0", "#,0", "Data health")
ms("Open Exceptions", "CALCULATE ( COUNTROWS ( Exceptions ), Exceptions[IsOpen] = TRUE () ) + 0", "#,0", "Exceptions")
ms("Lang", 'SELECTEDVALUE ( Language[Code], "EN" )', None, "Text")
def tmeasure(name, key):
    ms(name, f'''
        VAR k = "{key}"
        RETURN IF ( [Lang] = "ES", LOOKUPVALUE ( Translations[ES], Translations[Key], k ), LOOKUPVALUE ( Translations[EN], Translations[Key], k ) )
    ''', None, "Text")
for n, k in [("T Title", "rpt_title"), ("T Past Due", "kpi_pd"), ("T True Backlog", "kpi_tb"), ("T Critical", "kpi_cr"),
             ("T At Risk", "kpi_ar"), ("T Not Credited", "kpi_c1"), ("T Next Trucks", "ttl_trucks"), ("T Aging", "ttl_aging"),
             ("T Trend", "ttl_trend"), ("T Exceptions", "ttl_ex"), ("T Lines", "ttl_lines"), ("T Health", "ttl_health"),
             ("T ShipTo", "sl_shipto"), ("T Part", "sl_part"), ("T Status", "sl_status")]:
    tmeasure(n, k)
ms("T As Of", f'''
    VAR lbl = IF ( [Lang] = "ES", LOOKUPVALUE ( Translations[ES], Translations[Key], "lbl_asof" ), LOOKUPVALUE ( Translations[EN], Translations[Key], "lbl_asof" ) )
    RETURN lbl & " " & FORMAT ( {ASOF}, "ddd mmm d, yyyy" ) & "  |  " & FORMAT ( [Lines], "#,0" ) & " PO lines  |  " & FORMAT ( [Open Exceptions], "#,0" ) & " open exceptions"
''', None, "Text")
ms("KPI Sub Past Due", 'FORMAT ( [Past Due Lines], "#,0" ) & " lines  |  " & FORMAT ( [Missed Truck Not Yet Due Qty], "#,0" ) & " not yet due at Sub-Zero"', None, "Text")
ms("KPI Sub True Backlog", '"Sub-Zero shows " & FORMAT ( [SZ Past Due Qty], "#,0" ) & " past due"', None, "Text")
ms("KPI Sub Critical", 'FORMAT ( [Critical Lines], "#,0" ) & " lines not ready"', None, "Text")
ms("KPI Sub At Risk", 'FORMAT ( [At Risk Lines], "#,0" ) & " lines not ready"', None, "Text")
ms("KPI Sub Not Credited", 'FORMAT ( [C1 Lines], "#,0" ) & " lines to clear with Sub-Zero"', None, "Text")

table("Requirements", parts + M + [mpart("Requirements", req_m)])

# ------------------------------------------------------------------ other tables
table("ShipToSchedule", [col("ShipToKey", "string", "ShipToKey"), col("ShipToName", "string", "ShipToName"),
    col("TruckWeekday", "int64", "TruckWeekday"), col("TransitCalendarDays", "int64", "TransitCalendarDays"),
    col("DateBasis", "string", "DateBasis"), col("LoadDaysBefore", "int64", "LoadDaysBefore"),
    mpart("ShipToSchedule", csv_m(r"input\shipto_schedule.csv",
        ["ShipToKey", "ShipToName", "TruckWeekday", "TransitCalendarDays", "DateBasis", "LoadDaysBefore", "Active"],
        [("TruckWeekday", "Int64.Type"), ("TransitCalendarDays", "Int64.Type"), ("LoadDaysBefore", "Int64.Type")],
        extra=''',
        Result = Table.SelectRows(Typed, each [Active] <> "0")'''))])

table("Shipments", [col("ShipmentNo", "string", "ShipmentNo"), col("ReqKey", "string", "ReqKey"), col("StockCode", "string", "StockCode"),
    col("ShipQty", "double", "ShipQty", "#,0", "sum"), col("ShipDate", "dateTime", "ShipDate", "yyyy-mm-dd"),
    mpart("Shipments", csv_m(r"input\shipments.csv", ["ShipmentNo", "ReqKey", "StockCode", "ShipQty", "ShipDate"],
        [("ShipQty", "type number"), ("ShipDate", "type date")], extra=''',
        Result = Typed'''))])

table("FGInventory", [col("StockCode", "string", "StockCode"), col("Warehouse", "string", "Warehouse"),
    col("OnHandQty", "double", "OnHandQty", "#,0", "sum"),
    mpart("FGInventory", csv_m(r"input\fg_inventory.csv", ["StockCode", "Warehouse", "OnHandQty"],
        [("OnHandQty", "type number")], extra=''',
        Result = Typed'''))])

table("RunInfo", [col("AsOfDate", "dateTime", "AsOfDate", "yyyy-mm-dd"), col("RefreshedAt", "dateTime", "RefreshedAt", "yyyy-mm-dd hh:nn"),
    mpart("RunInfo", '''
    let
        // Plant time (Eastern, standard offset). Set AsOfOverride (yyyy-mm-dd) to replay a past day.
        NowET = DateTimeZone.SwitchZone(DateTimeZone.UtcNow(), -5),
        AsOf = if AsOfOverride <> null and Text.Trim(AsOfOverride) <> "" then Date.FromText(Text.Trim(AsOfOverride)) else Date.From(NowET),
        Result = #table(type table [AsOfDate = date, RefreshedAt = datetime], {{AsOf, DateTime.From(NowET)}})
    in
        Result
    ''')])

table("Holidays", [col("Date", "dateTime", "Date", "yyyy-mm-dd"),
    mpart("Holidays", '''
    let
        Source = Csv.Document(File.Contents(DataFolder & "input\\SZW_Config.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
        Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
        Row = Table.SelectRows(Promoted, each [Key] = "Holidays"),
        Raw = if Table.IsEmpty(Row) then "" else Row{0}[Value],
        Items = List.Select(List.Transform(Text.Split(Raw, ";"), Text.Trim), each _ <> ""),
        Result = Table.FromList(List.Transform(Items, each Date.FromText(_)), Splitter.SplitByNothing(), type table [Date = date])
    in
        Result
    ''')])

table("BizCalendar", [col("Date", "dateTime", "[Date]", "yyyy-mm-dd", inferred=True),
    col("IsBusinessDay", "boolean", "[IsBusinessDay]", inferred=True),
    cpart("BizCalendar", '''
    VAR h = SELECTCOLUMNS ( Holidays, "D", Holidays[Date] )
    RETURN
        ADDCOLUMNS (
            CALENDAR ( DATE ( 2025, 1, 1 ), DATE ( 2027, 12, 31 ) ),
            "IsBusinessDay", WEEKDAY ( [Date], 2 ) <= 5 && NOT ( [Date] IN h ) )
    ''')])

table("Parts", [col("StockCode", "string", "StockCode"), col("Description", "string", "Description"),
    mpart("Parts", '''
    let
        Req = Table.PromoteHeaders(Csv.Document(File.Contents(DataFolder & "input\\requirements.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]), [PromoteAllScalars = true]),
        Exc = Table.PromoteHeaders(Csv.Document(File.Contents(DataFolder & "output\\exceptions_register.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]), [PromoteAllScalars = true]),
        A = Table.SelectColumns(Table.RenameColumns(Req, {{"StockDescription", "Description"}}), {"StockCode", "Description"}),
        B = Table.AddColumn(Table.RenameColumns(Table.SelectColumns(Exc, {"Part"}), {{"Part", "StockCode"}}), "Description", each null, type text),
        Both = Table.Combine({A, B}),
        Clean = Table.SelectRows(Both, each [StockCode] <> null and [StockCode] <> ""),
        Sorted = Table.Sort(Clean, {{"Description", Order.Descending}}),
        Result = Table.Distinct(Sorted, {"StockCode"})
    in
        Result
    ''')])

exc_cols = ["ExceptionKey", "RuleID", "Severity", "Status", "Part", "Customer", "ShipTo", "ReqKey", "Truck", "Detail"]
table("Exceptions", [*(col(c, "string", c) for c in exc_cols),
    col("ReqShipDate", "dateTime", "ReqShipDate", "yyyy-mm-dd"), col("FirstDetected", "dateTime", "FirstDetected", "yyyy-mm-dd"),
    col("OpenQty", "double", "OpenQty", "#,0", "sum"), col("ShortQty", "double", "ShortQty", "#,0", "sum"),
    col("DaysPastDue", "int64", "DaysPastDue", "0"), col("Owners", "string", "Owners"), col("RuleDescription", "string", "RuleDescription"),
    col("IsOpen", "boolean", "IsOpen"),
    mpart("Exceptions", '''
    let
        // v0.1 reads the agent's exception register; production reads the SharePoint list SZW_Exceptions
        Source = Csv.Document(File.Contents(DataFolder & "output\\exceptions_register.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
        Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
        Blanks = Table.ReplaceValue(Promoted, "", null, Replacer.ReplaceValue, {"ReqShipDate", "FirstDetected", "OpenQty", "ShortQty", "DaysPastDue"}),
        Typed = Table.TransformColumnTypes(Blanks, {{"ReqShipDate", type date}, {"FirstDetected", type date}, {"OpenQty", type number}, {"ShortQty", type number}, {"DaysPastDue", Int64.Type}}, "en-US"),
        Routing = Table.PromoteHeaders(Csv.Document(File.Contents(DataFolder & "input\\SZW_Routing.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]), [PromoteAllScalars = true]),
        People = [#"cnixon@millsproducts.com" = "Celia", #"jzacarias@millsproducts.com" = "JC", #"twilcox@millsproducts.com" = "Tiffany",
                  #"bjhonson@millsproducts.com" = "Brian", #"rrandolph@millsproducts.com" = "Robert", #"rpadron@millsproducts.com" = "Ricardo",
                  #"tsledge@millsproducts.com" = "Tonya", #"mmcmillin@millsproducts.com" = "Matt", #"dgutierrez@millsproducts.com" = "Daniel"],
        Joined = Table.NestedJoin(Typed, {"RuleID"}, Routing, {"RuleID"}, "R", JoinKind.LeftOuter),
        Expanded = Table.ExpandTableColumn(Joined, "R", {"Description", "NotifyEmails"}, {"RuleDescription", "NotifyEmails"}),
        Owners = Table.AddColumn(Expanded, "Owners", each Text.Combine(List.Transform(List.Select(Text.Split([NotifyEmails] ?? "", ";"), each _ <> ""), each Record.FieldOrDefault(People, Text.Lower(Text.Trim(_)), _)), ", "), type text),
        IsOpen = Table.AddColumn(Owners, "IsOpen", each List.Contains({"New", "Acknowledged", "Recovery planned"}, [Status]), type logical),
        Result = Table.SelectColumns(IsOpen, {"ExceptionKey", "RuleID", "Severity", "Status", "Part", "Customer", "ShipTo", "ReqKey", "Truck", "Detail", "ReqShipDate", "FirstDetected", "OpenQty", "ShortQty", "DaysPastDue", "Owners", "RuleDescription", "IsOpen"})
    in
        Result
    ''')])

table("BacklogSnapshot", [col("SnapshotDate", "dateTime", "SnapshotDate", "yyyy-mm-dd"), col("StockCode", "string", "StockCode"),
    col("PastDueQty", "double", "PastDueQty", "#,0", "sum"),
    mpart("BacklogSnapshot", '''
    let
        // Daily snapshot files written by the agent (production: flow F3 to SharePoint SZW_Agent/Snapshots)
        Files = Folder.Files(DataFolder & "output"),
        Snaps = Table.SelectRows(Files, each Text.StartsWith([Name], "snapshot_") and [Extension] = ".csv"),
        Parsed = Table.AddColumn(Snaps, "T", each Table.PromoteHeaders(Csv.Document([Content], [Delimiter = ",", Encoding = 65001]), [PromoteAllScalars = true])),
        Combined = Table.Combine(Parsed[T]),
        Result = Table.TransformColumnTypes(Combined, {{"SnapshotDate", type date}, {"StockCode", type text}, {"PastDueQty", type number}}, "en-US")
    in
        Result
    ''')])

table("EngineCheck", [col("ReqKey", "string", "ReqKey"), col("Status", "string", "Status"),
    col("OpenQty", "double", "OpenQty", "#,0", "sum"), col("ShortQty", "double", "ShortQty", "#,0", "sum"),
    mpart("EngineCheck", csv_m(r"output\backlog_report.csv", ["ReqKey", "Status", "OpenQty", "ShortQty"],
        [("OpenQty", "type number"), ("ShortQty", "type number")], extra=''',
        Result = Typed'''))])

table("Language", [col("Code", "string", "[Code]", inferred=True, sortby="Order"), col("Order", "int64", "[Order]", inferred=True, hidden=True),
    cpart("Language", '''
    DATATABLE ( "Code", STRING, "Order", INTEGER, { { "EN", 1 }, { "ES", 2 } } )
    ''')])

tr = [("rpt_title", "Sub-Zero/Wolf Shipment & Backlog Monitor", "Monitor de Embarques y Backlog Sub-Zero/Wolf"),
      ("lbl_asof", "Data as of", "Datos al"),
      ("kpi_pd", "Past due: missed the truck", "Atrasado: perdió el camión"),
      ("kpi_tb", "True backlog: due date passed, not shipped", "Backlog real: vencido y sin enviar"),
      ("kpi_cr", "Critical: not ready for the next truck", "Crítico: no listo para el próximo camión"),
      ("kpi_ar", "At risk: not ready for the truck after", "En riesgo: no listo para el siguiente camión"),
      ("kpi_c1", "Shipped, still open at Sub-Zero", "Enviado, aún abierto en Sub-Zero"),
      ("ttl_trucks", "Next trucks", "Próximos camiones"),
      ("ttl_aging", "Past due by part and age", "Atraso por parte y antigüedad"),
      ("ttl_trend", "Past-due trend (daily snapshots)", "Tendencia de atraso (fotos diarias)"),
      ("ttl_ex", "Open exceptions", "Excepciones abiertas"),
      ("ttl_lines", "All Sub-Zero PO lines", "Todas las líneas de OC de Sub-Zero"),
      ("ttl_health", "Model vs. agent engine (must match)", "Modelo vs. motor del agente (deben coincidir)"),
      ("sl_shipto", "Ship-to", "Destino"), ("sl_part", "Part", "Parte"), ("sl_status", "Status", "Estatus")]
rows = ",\n".join('{ "%s", "%s", "%s" }' % r for r in tr)
table("Translations", [col("Key", "string", "[Key]", inferred=True), col("EN", "string", "[EN]", inferred=True),
    col("ES", "string", "[ES]", inferred=True),
    cpart("Translations", 'DATATABLE ( "Key", STRING, "EN", STRING, "ES", STRING, {\n' + rows + '\n} )')])

# ------------------------------------------------------------------ model-level files
(DEF / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1567\n", encoding="utf-8")
tables = ["Requirements", "ShipToSchedule", "Shipments", "FGInventory", "RunInfo", "Holidays", "BizCalendar", "Parts",
          "Exceptions", "BacklogSnapshot", "EngineCheck", "Language", "Translations"]
(DEF / "model.tmdl").write_text(
    "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US\n"
    "\tdataAccessOptions\n\t\tlegacyRedirects\n\t\treturnErrorValuesAsNull\n\n"
    "annotation __PBI_TimeIntelligenceEnabled = 0\n\n"
    + "".join(f"ref table {t}\n" for t in tables), encoding="utf-8")
(DEF / "expressions.tmdl").write_text(
    'expression DataFolder = "C:\\SZW_Backlog_Monitor\\Data\\" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
    '\tannotation PBI_ResultType = Text\n\n'
    'expression AsOfOverride = "2026-10-28" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=false]\n'
    '\tannotation PBI_ResultType = Text\n', encoding="utf-8")
rels = [("Requirements.ShipToKey", "ShipToSchedule.ShipToKey"), ("Exceptions.ShipTo", "ShipToSchedule.ShipToKey"),
        ("Requirements.StockCode", "Parts.StockCode"), ("Exceptions.Part", "Parts.StockCode")]
(DEF / "relationships.tmdl").write_text("".join(
    f"relationship rel_{a.replace('.', '_')}\n\tfromColumn: {a}\n\ttoColumn: {b}\n\n" for a, b in rels), encoding="utf-8")
print("model written:", sorted(p.name for p in (DEF / "tables").iterdir()))
