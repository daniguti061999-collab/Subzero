# Sub-Zero/Wolf Shipment & Backlog Monitoring Agent — Build Plan

Oct 27, 2026 · @Daniel

## 1. Executive summary

Build the pilot on what Mills Products already has: scheduled ERP exports land in SharePoint, a Power BI semantic model calculates backlog and risk, and Power Automate flows run the monitoring, alerting and history on a schedule. No conversational session needs to stay open.

**What it does, every hour of the business day, for every active Sub-Zero/Wolf part:**

- Reconciles customer requirements (sales order lines and releases) against shipments.
- Splits open demand into four buckets: past-due backlog, due today, due within 7 days, and due within 30 days.
- Nets finished-goods inventory against requirements in due-date order. It flags At Risk and Critical lines before the ship date, not after.
- Opens one exception per problem, posts it to the right Teams channel, tracks acknowledgment and escalates if nobody acts.
- Saves a daily backlog snapshot, so trend, aging and day-over-day change are auditable.
- Sends a 7:00 AM exception summary and a Monday performance report.

**Business value:** fewer missed Sub-Zero/Wolf commitments, issues found hours or days earlier, and the manual backlog spreadsheet retired once the parallel run proves the numbers match.

**Why this approach (Option A, built to grow into Option C):** every component runs on Microsoft 365 and Power BI/Fabric, which your team already supports. All calculations are deterministic and visible in DAX or Power Query. AI is added only where it helps: writing the daily narrative and answering questions about the exception data. It never calculates quantities or changes ERP records.

**Guardrail:** the agent reads, calculates, alerts and recommends. It never changes customer orders, production schedules, inventory balances or shipping transactions.

**Assumptions** (updated Oct 27, see section 14): SYSPRO data comes over SQL through the existing semantic model, and shipped quantity is held per release. The workspace behind your shared Fabric link is where the new model will live. I couldn't open that link from here, so the design does not depend on its current contents.

## 2. Recommended architecture

The architecture has four layers: ERP exports in SharePoint, one semantic model that does all the calculating, five Power Automate flows that run on schedules, and the alert/exception outputs people act on.

&#91;embedded content: Pilot architecture · ERP exports to people, 5 flows\]

The model is the only place quantities and statuses are calculated. Flows only move files, query the model, and send and track messages. Phase 2 swaps the SharePoint files for Fabric Lakehouse tables under the same model, with no change to the flows or the report.

## 3. Data requirements

The pilot needs three ERP exports: open order lines, shipments and FG inventory. Everything else is Phase 2. The ERP stays the source of truth, and the agent only reads copies of its data.

### Sources and integration method

| # | Source | Used for | Pilot method | Refresh | Phase |
| --- | --- | --- | --- | --- | --- |
| 1 | ERP open sales order lines | Requirements, open balance, price | Scheduled CSV export to SharePoint | Hourly, 6 AM–6 PM | 1 |
| 2 | Customer releases / EDI (830/862 or portal) | Release numbers, demand changes | Through the ERP if releases load into SO lines. Otherwise a separate file | Each release load | 1 if releases live outside the ERP |
| 3 | FG inventory (on hand, allocated, hold) | Coverage and At Risk | Scheduled CSV export | Hourly | 1 |
| 4 | Shipments / dispatch / packing slips | Shipped qty, ship date, completion | Scheduled CSV export (or line ship qty in source 1) | Hourly | 1 |
| 5 | Work orders / production schedule / WIP | Projected supply | CSV export or SQL view | 2–4× per shift | 2 |
| 6 | Carrier tracking | Delivered vs. left the dock | Carrier portal export or API | Daily | 3 |
| 7 | Shipment and demand history | OTD, trend, forecast error | One-time back-load (12 months) + daily snapshot | Daily | 1 (back-load) |
| 8 | Part master + customer-part cross-reference | Part grouping, customer part no., planner | Export, low change | Weekly | 1 |

To confirm for each source: does the ERP expose it as a report that can be scheduled, a SQL view (through the on-premises data gateway), or an API? The pilot works with scheduled files alone.

### Minimum fields for the proof of concept

**OpenOrders\_YYYYMMDD\_HHMM.csv** (one row per sales order line or release):

```csv
Customer,CustomerName,SalesOrder,SOLine,CustomerPO,ReleaseNo,StockCode,CustomerPartNo,OrderQty,ShippedQty,OpenQty,RequiredShipDate,RequiredDeliveryDate,LineStatus,UnitPrice,LastChangeDate
```

**Shipments\_YYYYMMDD\_HHMM.csv** (one row per shipment line, rolling 120 days):

```csv
ShipmentNo,PackingSlip,SalesOrder,SOLine,ReleaseNo,StockCode,ShipQty,ShipDate,Carrier,TrackingNo,ShipStatus,ReversalFlag
```

**FGInventory\_YYYYMMDD\_HHMM.csv** (one row per part per warehouse):

```csv
StockCode,Warehouse,OnHandQty,AllocatedQty,QualityHoldQty,AvailableQty
```

### Additional fields for predictive monitoring (Phase 2)

- **Work orders:** Job, StockCode, QtyToMake, QtyCompleted, ScheduledFinishDate, Work center, Job status.
- **Material shortages:** Job, Component, Required, Issued, Shortage qty, Expected receipt date.
- **Capacity and performance:** daily completions by part (last 90 days), shipping cutoff time, truck schedule.
- **Quality holds:** Hold qty, Hold reason, Expected release date.

### Refresh, validation and source-of-truth rules

| Rule | Applies to | Behavior if it fails |
| --- | --- | --- |
| Header check: exact expected column names | Every file | Reject the file, keep the last good data, alert the owner |
| Freshness: newest file under 90 minutes old during business hours | Every source | "Stale data" banner on the dashboard. Alerts are suppressed and replaced with one data-health alert |
| Row-count change over ±30% vs. last file | Open orders, inventory | Load the file but hold alerts until a person confirms |
| Unique key (SalesOrder + SOLine + ReleaseNo) | Open orders | Duplicates are flagged and only the newest LastChangeDate is kept |
| OpenQty = OrderQty − ShippedQty | Open orders | ERP OpenQty wins. The difference is listed on the Data Health page |
| Shipment without SalesOrder/SOLine | Shipments | Not credited to any requirement. Listed as "Unmatched shipment" |
| Negative or reversed shipments (ReversalFlag) | Shipments | Netted against the original line, never double counted |
| Missing RequiredShipDate | Open orders | Excluded from due-window buckets and listed as an exception, not assumed |

The exports must be timestamped in plant local time (Eastern). Power BI Service evaluates `TODAY()` in UTC, so the model takes its as-of date from the export file name instead.

## 4. Agent workflows

The six "agents" (A–F) are logical roles. In the pilot they run as five scheduled Power Automate flows over one semantic model.

| Agent | Implemented as | Runs |
| --- | --- | --- |
| A Demand Monitor | Power Query (OpenOrders) + demand-change compare vs. prior snapshot | Each refresh |
| B Shipment Tracking | Power Query (Shipments) + matching logic, section 5 | Each refresh |
| C Backlog Monitor | DAX measures + daily snapshot file | Each refresh; snapshot 6:30 AM |
| D Predictive Shortage | Calculated columns: FG netting (Phase 1), supply projection (Phase 2) | Each refresh |
| E Alert & Escalation | Flows F2 (Monitor) and F4 (Escalation) + SharePoint `SZW_Exceptions` list | Hourly |
| F Reporting | Power BI report + flows F3 (Daily/Weekly summary) | Continuous; 7:00 AM daily; Monday 7:30 AM |

### F1 — Ingest (trigger: a file is created in `ERP_Exports/Incoming`)

1. Read the file name and get the type (OpenOrders / Shipments / FGInventory) and the export timestamp.
2. Validate: extension, size above 0, header row matches the template stored in `SZW_Config`.
3. Pass: copy to `ERP_Exports/Current/<type>.csv` (overwrite) and to `ERP_Exports/Archive/<yyyy>/<mm>/` (never overwrite). Fail: move to `Rejected/` and post a data-health alert.
4. When all three types have landed for the same hour (or 20 min after the first one), call **Power BI → Refresh a dataset**.
5. Write a row to `SZW_RunLog`: run ID, files, row counts, status.

### F2 — Monitor (recurrence: hourly at :15, 6 AM–6 PM, Mon–Sat)

1. Check the last refresh status (Power BI REST: refresh history). If it failed or the data is stale, send one data-health alert, log the run and stop. No business alerts go out on stale data.
2. **Run a query against a dataset**: the DAX exception query in section 5 returns every requirement whose status is not On Track, plus the backlog-change rows.
3. For each row, build `ExceptionKey = RuleID|SalesOrder|SOLine|ReleaseNo|RequiredShipDate`.
4. Look up the key in `SZW_Exceptions`:
   - **Not found:** create the item, notify the owner group (section 6), set LastNotified.
   - **Found, severity went up:** update the item and re-notify, marked "Escalated from Warning".
   - **Found, same severity:** update LastSeen and quantities only. No message.
5. Open items whose key no longer appears are set to **Auto-cleared** with the timestamp. Owners get no message; the clear shows in the daily summary.
6. Log the run: rows evaluated, new, updated, cleared, errors.

### F3 — Daily and weekly summary (6:30 AM snapshot, 7:00 AM daily, Monday 7:30 AM weekly)

1. 6:30 AM: query the model at part × due-date grain and write `Snapshot_YYYYMMDD.csv` to `ERP_Exports/Snapshots`. This is the backlog history.
2. 7:00 AM: query KPIs + top 10 exceptions and build the summary (section 12). Optionally pass the computed table to an AI prompt that writes the narrative (see below). Post to Teams and email the distribution list.
3. Monday: weekly OTD, demand vs. shipped, backlog trend, and the top 5 parts by exposure.

### F4 — Escalation (recurrence: every 30 min, business hours)

1. Query `SZW_Exceptions` where Status is New or Acknowledged, with no recovery plan.
2. If age is past the rule's escalation interval (from `SZW_Config`), raise EscalationLevel by 1, notify the next tier and record it.

### F5 — Watchdog (recurrence: every 2 hours, 24/7)

1. Alert the agent owner if: no file in 3 hours during business hours, two failed refreshes in a row, any flow run failed, or F2 did not log a run in 90 minutes.
2. Every flow has "configure run after → has failed" branches, 3 retries with exponential back-off on connector actions, and run-only users set to a service account, not a personal login.

### What AI adds beyond conventional automation

| AI function | Pilot? | Guardrail |
| --- | --- | --- |
| Write the daily summary narrative from the computed exception table | Yes (optional) | Gets only computed numbers. Every number in the text must match a table value, checked in the flow |
| Natural-language Q&A over the model ("why is SZ-2002 at risk?") | Phase 2 | Copilot in Power BI or a Fabric data agent; read-only |
| Recommend recovery actions from exception type + history of past resolutions | Phase 2 | Suggestions only, labeled as such, with the past cases they come from |
| Forecast late-risk from historical completion variance | Phase 3 | Only with 6+ months of snapshots; shown with a confidence band and next to the deterministic status, never replacing it |

Statuses, quantities and alerts are always deterministic. AI writes the explanations; it does not decide what is late.

## 5. Backlog calculation methodology

Each requirement (sales order line + release) gets credited quantity, open quantity, days past due, projected shortage and one status. All of it is calculated at refresh from ERP data, with no manual inputs.

### Definitions

- **Requirement** = one row of `SalesOrder | SOLine | ReleaseNo` with a required **ship** date. Delivery date is kept for reference only. Past due is always measured against the ship date.
- **Past-due backlog** = open quantity on requirements whose ship date is before the as-of date.
- **Current requirement** = ship date equals the as-of date. **Future demand** = ship date after the as-of date.
- **Projected shortage** = open quantity not covered by FG available (Phase 1), or by FG plus scheduled completions (Phase 2), netted in ship-date order.

```latex
\text{Credited}_r = \min\Big(Q_r,\ \max\big(0,\ S_{line} - \textstyle\sum_{j<r} Q_j\big)\Big)
```

```latex
\text{Open}_r = Q_r - \text{Credited}_r \qquad \text{PastDue} = \sum_{r\,:\,d_r < \text{AsOf}} \text{Open}_r
```

```latex
\text{Short}_r = \min\Big(\text{Open}_r,\ \max\big(0,\ \textstyle\sum_{j \le r,\ same\ part} \text{Open}_j - \text{FGAvail}_{part}\big)\Big)
```

Here Q is the release quantity, S is the net quantity shipped on the sales order line (reversals subtracted), j < r means releases on the same line with an earlier ship date, and the shortage sum runs over all open requirements for the part in ship-date order. Past-due requirements therefore use inventory first.

### Shipment-to-requirement matching (in priority order)

| Method | When | Confidence shown |
| --- | --- | --- |
| ERP release-level shipped qty | Export already carries shipped qty per release | Exact |
| Direct: shipment carries ReleaseNo | Release on the packing slip | Exact |
| Cumulative FIFO on the SO line (formula above) | Shipment has SO + line, not the release | Allocated (flagged) |
| Unmatched | No SO/line on the shipment | Not credited. Raises a Data exception |

The cumulative method needs no row-by-row allocation, so anyone can check it by hand. Every requirement shows its MatchMethod, so an allocated credit is never presented as exact.

### Double-counting controls

- Requirements are keyed on SalesOrder + SOLine + ReleaseNo. A revised release replaces the earlier row (newest LastChangeDate wins); it is not added.
- Cancelled lines (LineStatus = Cancelled) and order quantity reduced to the shipped quantity drop out of open quantity. The change is logged as a demand change, not as a shipment.
- Shipments are keyed on ShipmentNo + SO line. Reversals net against the original. A shipment appearing in two exports is counted once.
- ERP OpenQty is the source of truth. The calculated OpenQty is a cross-check, and any difference goes on the Data Health page.

### Power Query — load the current open-orders file

```
let
    Site     = "https://millsproductstn.sharepoint.com/sites/<OpsSite>",
    Files    = SharePoint.Files(Site, [ApiVersion = 15]),
    Current  = Table.SelectRows(Files, each Text.Contains([Folder Path], "/ERP_Exports/Current/") and [Name] = "OpenOrders.csv"),
    Csv      = Csv.Document(Current{0}[Content], [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Headers  = Table.PromoteHeaders(Csv, [PromoteAllScalars = true]),
    Typed    = Table.TransformColumnTypes(Headers, {
                 {"SalesOrder", type text}, {"SOLine", Int64.Type}, {"ReleaseNo", type text},
                 {"StockCode", type text}, {"OrderQty", type number}, {"ShippedQty", type number},
                 {"OpenQty", type number}, {"RequiredShipDate", type date}, {"UnitPrice", type number},
                 {"LastChangeDate", type datetime}}, "en-US"),
    SZW      = Table.SelectRows(Typed, each List.Contains(CustomerCodes_SZW, [Customer])),
    Active   = Table.SelectRows(SZW, each [LineStatus] <> "Cancelled"),
    Keyed    = Table.AddColumn(Active, "ReqKey", each [SalesOrder] & "|" & Text.From([SOLine]) & "|" & ([ReleaseNo] ?? "0"), type text),
    LineKey  = Table.AddColumn(Keyed, "LineKey", each [SalesOrder] & "|" & Text.From([SOLine]), type text),
    Dedup    = Table.Distinct(Table.Sort(LineKey, {{"LastChangeDate", Order.Descending}}), {"ReqKey"})
in
    Dedup
```

`CustomerCodes_SZW` is a list query read from `SZW_Config`, so adding customers later is a config change, not a code change. `RunInfo[AsOfDate]` is parsed from the archived file name (for example `OpenOrders_20261027_0600.csv`).

### DAX — calculated columns on Requirements

```
CumReqBefore =
VAR k = Requirements[LineKey]
VAR d = Requirements[RequiredShipDate]
VAR r = Requirements[ReqKey]
RETURN
    SUMX (
        FILTER ( ALL ( Requirements ),
            Requirements[LineKey] = k
                && ( Requirements[RequiredShipDate] < d
                     || ( Requirements[RequiredShipDate] = d && Requirements[ReqKey] < r ) ) ),
        Requirements[OrderQty] ) + 0

LineShippedQty =
VAR k = Requirements[LineKey]
RETURN CALCULATE ( MAX ( Requirements[ShippedQty] ), ALL ( Requirements ), Requirements[LineKey] = k )

CreditedQty = MIN ( Requirements[OrderQty], MAX ( 0, Requirements[LineShippedQty] - Requirements[CumReqBefore] ) )
OpenQtyCalc = Requirements[OrderQty] - Requirements[CreditedQty]

DaysPastDue =
VAR asof = MAX ( RunInfo[AsOfDate] )
RETURN IF ( Requirements[OpenQty] > 0 && Requirements[RequiredShipDate] < asof, INT ( asof - Requirements[RequiredShipDate] ), 0 )

AgingBucket =
SWITCH ( TRUE (),
    Requirements[DaysPastDue] = 0, "Not past due",
    Requirements[DaysPastDue] <= 2, "1-2 days",
    Requirements[DaysPastDue] <= 7, "3-7 days",
    Requirements[DaysPastDue] <= 14, "8-14 days",
    "15+ days" )

CumOpenByPart =
VAR p = Requirements[StockCode]
VAR d = Requirements[RequiredShipDate]
VAR r = Requirements[ReqKey]
RETURN
    SUMX (
        FILTER ( ALL ( Requirements ),
            Requirements[StockCode] = p
                && ( Requirements[RequiredShipDate] < d
                     || ( Requirements[RequiredShipDate] = d && Requirements[ReqKey] <= r ) ) ),
        Requirements[OpenQty] )

ProjectedShortQty =
MIN ( Requirements[OpenQty], MAX ( 0, Requirements[CumOpenByPart] - RELATED ( Parts[FGAvailableQty] ) ) )

WorkdaysToShip = NETWORKDAYS ( MAX ( RunInfo[AsOfDate] ), Requirements[RequiredShipDate] ) - 1

RiskStatus =
VAR asof = MAX ( RunInfo[AsOfDate] )
VAR critWD = MAX ( Config[CriticalWorkdays] )   -- default 1
VAR riskWD = MAX ( Config[AtRiskWorkdays] )     -- default 5
RETURN
    SWITCH ( TRUE (),
        Requirements[OpenQty] <= 0, "Complete",
        ISBLANK ( Requirements[RequiredShipDate] ), "Data Issue",
        Requirements[RequiredShipDate] < asof, "Past Due",
        Requirements[ProjectedShortQty] > 0 && Requirements[WorkdaysToShip] <= critWD, "Critical",
        Requirements[ProjectedShortQty] > 0 && Requirements[WorkdaysToShip] <= riskWD, "At Risk",
        "On Track" )
```

`LineShippedQty` takes the ERP's shipped-to-date for the SO line. Use it when the export is at release level but shipped quantity is held only at line level. `Parts[FGAvailableQty]` = `CALCULATE ( SUM ( Inventory[AvailableQty] ) )` as a column on Parts; it excludes quality-hold stock.

### DAX — measures

```
As Of Date = MAX ( RunInfo[AsOfDate] )
Open Qty = SUM ( Requirements[OpenQty] )
Past Due Qty = CALCULATE ( [Open Qty], Requirements[RiskStatus] = "Past Due" )
Past Due $ = SUMX ( FILTER ( Requirements, Requirements[RiskStatus] = "Past Due" ), Requirements[OpenQty] * Requirements[UnitPrice] )
Due Today Qty = VAR d = [As Of Date] RETURN CALCULATE ( [Open Qty], Requirements[RequiredShipDate] = d )
Due Next 7 Days Qty = VAR d = [As Of Date] RETURN CALCULATE ( [Open Qty], Requirements[RequiredShipDate] > d, Requirements[RequiredShipDate] <= d + 7 )
Due Next 30 Days Qty = VAR d = [As Of Date] RETURN CALCULATE ( [Open Qty], Requirements[RequiredShipDate] > d, Requirements[RequiredShipDate] <= d + 30 )
Shipped Today Qty = VAR d = [As Of Date] RETURN CALCULATE ( SUM ( Shipments[ShipQty] ), Shipments[ShipDate] = d )
Projected Short Qty = CALCULATE ( SUM ( Requirements[ProjectedShortQty] ), Requirements[RiskStatus] IN { "At Risk", "Critical" } )

OTD % (Lines) =
VAR asof = [As Of Date]
VAR dueLines = FILTER ( Requirements, Requirements[RequiredShipDate] < asof && Requirements[OrderQty] > 0 )
VAR onTime = FILTER ( dueLines, Requirements[CreditedByDueQty] >= Requirements[OrderQty] )
RETURN DIVIDE ( COUNTROWS ( onTime ), COUNTROWS ( dueLines ) )

Past Due Qty Prior Snapshot =
VAR asof = [As Of Date]
VAR prev = CALCULATE ( MAX ( BacklogSnapshot[SnapshotDate] ), BacklogSnapshot[SnapshotDate] < asof )
RETURN CALCULATE ( SUM ( BacklogSnapshot[PastDueQty] ), BacklogSnapshot[SnapshotDate] = prev )

Past Due Change % = DIVIDE ( [Past Due Qty] - [Past Due Qty Prior Snapshot], [Past Due Qty Prior Snapshot] )
```

`CreditedByDueQty` is the `CreditedQty` pattern computed only on shipments with `ShipDate <= RequiredShipDate`. For OTD, the open-orders export must also include lines completed in the last 120 days.

### DAX query used by the Monitor flow (F2)

```
EVALUATE
CALCULATETABLE (
    SELECTCOLUMNS ( Requirements,
        "ReqKey", Requirements[ReqKey], "Customer", Requirements[Customer],
        "Part", Requirements[StockCode], "SalesOrder", Requirements[SalesOrder],
        "SOLine", Requirements[SOLine], "ReleaseNo", Requirements[ReleaseNo],
        "ShipDate", Requirements[RequiredShipDate], "OpenQty", Requirements[OpenQty],
        "ShortQty", Requirements[ProjectedShortQty], "DaysPastDue", Requirements[DaysPastDue],
        "Status", Requirements[RiskStatus], "Match", Requirements[MatchMethod] ),
    Requirements[RiskStatus] IN { "Past Due", "Critical", "At Risk", "Data Issue" }
)
```

### Note on your existing measure `A_ExcessMtlsCostBySales`

It can live in the same workspace. Two things to check in it:

- `VAR QtyBySales` is declared but never used. Remove it.
- `SELECTEDVALUE ( ExcessInventory[Component_UnitCost] )` returns BLANK when a component has more than one distinct cost (for example, two warehouses with different costs). That component then adds $0 with no warning. Use `MAX`, or a quantity-weighted average, and add a check measure that counts components with more than one cost.

## 6. Alerting system

Each alert rule is a row in the SharePoint list `SZW_Config`. Planners and managers change thresholds, recipients and escalation times there without editing a flow. Each problem gets one exception record; repeat runs update that record instead of posting again.

### Rules (defaults, all configurable)

| Rule | Condition | Level | First notify | Escalate if no recovery plan after | Escalate to |
| --- | --- | --- | --- | --- | --- |
| R1 Short in 48 h | ProjectedShortQty > 0 and WorkdaysToShip ≤ 2 | Warning | Planning | 8 business hours | Planning manager |
| R2 No plan in 24 h | RiskStatus = Critical and no recovery plan on the exception | Critical | Planning + Shipping | 4 business hours | Operations manager |
| R3 Missed ship date | RiskStatus = Past Due (new) | Critical | Operations + Planning + Shipping | 24 h | Plant / Ops management |
| R4 Backlog growth | Past Due Change % > 10% vs. prior snapshot (customer level) | Warning | Supply chain | Next daily summary | Supply chain manager |
| R5 Critical unresolved | Any Critical or Past Due exception open > 24 h with no plan | Escalation | Management | 24 h | General manager |
| R6 Future demand > supply | Phase 2: projected supply < demand within the horizon | Predictive | Production planning | Weekly review | — |
| R7 Demand change | Release qty up > 15% or date pulled in within 10 workdays | Warning | Planning | — | — |
| D1 Data health | Stale file, failed refresh, header mismatch, unmatched shipments | System | Agent owner | 2 h | IT / BI support |

### Deduplication and lifecycle

- **Key:** `RuleID|SalesOrder|SOLine|ReleaseNo|RequiredShipDate` (R4 uses `R4|Customer|SnapshotDate`).
- **Statuses:** New → Acknowledged → Recovery planned → Resolved, or Auto-cleared when the condition disappears from the data.
- **Re-notify only when** severity goes up, the shortage grows more than 20%, or an escalation interval passes.
- **Grouping:** if more than 5 new exceptions for the same owner come in one run, send one digest card listing them, not five messages.
- **Quiet hours:** outside 6 AM–6 PM, only R3 and D1 send messages. Everything else waits for the 7:00 AM summary.

### SharePoint list `SZW_Exceptions` (exception register and audit trail)

| Column | Type | Notes |
| --- | --- | --- |
| ExceptionKey | Text, indexed, unique | Dedup key |
| RuleID, Severity | Choice | From the rule table |
| Customer, Part, SalesOrder, SOLine, ReleaseNo | Text |  |
| RequiredShipDate | Date |  |
| OpenQty, ShortQty, DaysPastDue | Number | Updated each run |
| Status | Choice | New / Acknowledged / Recovery planned / Resolved / Auto-cleared |
| OwnerGroup, AssignedTo | Choice / Person |  |
| RecoveryPlan, RecoveryDate | Multi-line text / Date | Filled in by the owner |
| FirstDetected, LastSeen, LastNotified, ClearedAt | Date-time |  |
| EscalationLevel | Number | 0–3 |
| RunID | Text | Links to `SZW_RunLog` |

List versioning stays on, so every status change keeps who changed it and when.

### Message templates (Teams adaptive card; email uses the same text)

- **R3 Past due:** "\[CRITICAL\] Part {Part} — SO {SalesOrder}/{SOLine} rel {ReleaseNo} is past due by {OpenQty} units ({DaysPastDue} day(s)). Due {ShipDate}. FG available now: {FGAvail}. Review inventory, production completion dates and recovery shipment options." Buttons: *Open exception* · *View part in Power BI*.
- **R2 Critical shortage:** "\[CRITICAL\] Part {Part} has a projected {ShortQty}-unit shortage for the {ShipDate} shipment ({OpenQty} required, {FGAvail} available). No recovery plan recorded. Review production recovery options and notify the responsible planner."
- **R4 Backlog growth:** "\[WARNING\] {Customer} past-due backlog is {PastDueQty} units, up {Pct}% ({Delta} units) since {PriorDate}. Top contributors: {Top3Parts}."
- **D1 Data health:** "\[SYSTEM\] {Source} export is {Minutes} min old / refresh failed at {Time}. Business alerts are paused until data is current."

### Acknowledgment

Pilot: the card's *Open exception* button opens the SharePoint item. The owner sets Status and RecoveryPlan there. F4 reads those fields to decide whether to escalate. Phase 2 can add a small Power Apps form or adaptive-card buttons that write back directly.

## 7. Dashboard design

One Power BI report, six pages, every number traceable to a requirement row. Global slicers: Customer, Part, Ship date, RiskStatus, Planner. Every page shows the as-of timestamp and a red banner when the data is stale.

| Page | Purpose | Visuals | Drill to |
| --- | --- | --- | --- |
| 1 Overview | Where do we stand right now? | KPI cards: Open, Past Due qty and $, Due Today, Shipped Today, At Risk/Critical, OTD % (MTD). Line: past-due trend, 60 days (snapshots). Clustered columns: weekly required vs. shipped, 12 weeks | Pages 3 and 4 |
| 2 Ship window | What must ship today, tomorrow, this week, next 30 days? | Matrix: Part × ship date (next 10 workdays), conditional format by status. Table: due today with FG available and shortage | Part drillthrough |
| 3 Backlog & aging | Where is the backlog and how old is it? | Stacked bars: past-due qty by part × aging bucket (1–2, 3–7, 8–14, 15+). Table: part, past-due qty, $, oldest date, change vs. yesterday and last week | Part drillthrough |
| 4 Exceptions | What needs action? | Table from `SZW_Exceptions`: rule, severity, owner, status, age, recovery plan. Bars: open exceptions by owner group | SharePoint item link |
| 5 Part drillthrough | Everything about one part | Requirements with match method, shipments, FG by warehouse, exception history, 30-day demand vs. shipped | — |
| 6 Data health | Can we trust the numbers? | File freshness per source, row counts, rejected files, unmatched shipments, ERP vs. calculated OpenQty differences, flow run log | — |

Status colors are used the same way everywhere: Past Due red, Critical orange, At Risk amber, On Track grey. Colors are always paired with the status word, never color alone.

Row-level security: planners can see all Sub-Zero/Wolf data in the pilot. When other customers are added, roles filter by customer group (section 10).

## 8. Implementation options

Recommendation: **Option A for the pilot**, structured so it becomes **Option C** without rebuilding. The calculation logic stays in the semantic model, and storage moves from SharePoint files to a Fabric Lakehouse when volume or customer count requires it.

| Criterion | A: Power Automate + Power BI + ERP exports | B: Custom Python/SQL service | C: Hybrid (A's deterministic core on Fabric + AI layer) |
| --- | --- | --- | --- |
| Added cost | Low. Uses existing M365, Power BI and Fabric licenses; check premium connector needs | Medium. Server or container, database, developer time | Medium. Fabric capacity (already in use?) + AI usage |
| Build time to pilot | 6–8 weeks | 10–14 weeks | 6–8 weeks for the A part, then additions |
| Complexity | Low–medium. Flows + DAX | High. Custom code, scheduler, auth, hosting | Medium |
| Maintainability by Ops/IT | High. Low-code, familiar tools | Low unless a developer stays assigned | Medium–high |
| Security | M365/Entra ID roles, SharePoint permissions, Power BI RLS | Must be built: service accounts, secrets, network | Same as A + AI data-access controls |
| Scalability | Fine for one customer and a few thousand lines; flow loops and SharePoint lists get slow at large volume | High | High. Lakehouse tables, notebooks or pipelines for heavy steps |
| Manual dependence | Only if the ERP can't schedule exports | None once deployed | None once deployed |
| Fit for NL Q&A and narratives | Basic (AI prompt step in a flow) | Full, custom | Full (Copilot / Fabric data agent over the same model) |

**Platform limits to confirm with IT before build** (from general knowledge; I could not check current Microsoft documentation from here, so treat as approximate):

- Scheduled refreshes per day: about 8 on a Pro-licensed workspace, about 48 on Premium/Fabric capacity. Hourly runs from 6 AM to 6 PM are 13 refreshes a day, so they need the workspace on Premium/Fabric capacity. On Pro, refresh about every 2 hours, which also applies to refreshes triggered by flow F1.
- "Run a query against a dataset" returns a capped result (roughly 100k rows). Fine for an exception list, not for full extracts.
- Fabric Activator can watch Power BI visuals and trigger Teams or Power Automate. It is a later alternative to flow F2 for simple threshold rules.
- Premium Power Automate connectors (HTTP, Dataverse) need per-user or per-flow licensing. The pilot design uses only SharePoint, Teams, Outlook and Power BI actions.

## 9. Sub-Zero/Wolf pilot plan

The pilot covers every active Sub-Zero/Wolf part and takes about 7 weeks from export setup. That includes a 10-business-day parallel run against the manual backlog report, which ends in a go/no-go decision. Proposed dates assume exports are scheduled by early November and allow for the Thanksgiving week.

&#91;embedded content: Pilot timeline · 6 workstreams, Nov 2 to Dec 21\]

Reconciliation starts before the model is finished, so logic errors show up while there is still time to fix them before the parallel run.

| Workstream | Dates (proposed) | Key tasks | Depends on |
| --- | --- | --- | --- |
| 0 Discovery & exports | Nov 2 – Nov 6 | Answer section 14; build the three ERP export reports; schedule them to SharePoint; agree on the SZW customer code list | ERP admin |
| 1 Data model | Nov 9 – Nov 20 | Power Query loads, keys, matching, calculated columns, measures; Data Health page | Workstream 0 |
| 2 Historical reconciliation | Nov 16 – Nov 25 | Rebuild 10 past days from archived exports; compare to the manual backlog line by line; fix logic | Workstream 1, manual reports for those days |
| 3 Flows & exception register | Nov 23 – Dec 4 | F1–F5, `SZW_Exceptions`, `SZW_Config`, `SZW_RunLog`, Teams channel, service account | Workstream 1 |
| 4 Parallel run | Dec 7 – Dec 18 | Agent and manual process run side by side; daily 15-min review of differences | Workstreams 2–3 |
| 5 Go/no-go | Dec 21 | Review acceptance metrics; decide to retire the manual report | Workstream 4 |

### Validation method

- **Reconciliation:** each day, export the agent's past-due list and the manual list. Join them on SO + line + release and classify every difference: agent wrong, manual wrong, or timing. Only "agent wrong" counts against the agent.
- **Missed exceptions:** any late or short shipment found by people that the agent did not flag at least 24 h ahead (when the data allowed it).
- **False alerts:** alerts the owner marks "not a real issue" with a reason code.

### Acceptance criteria (proposed, to agree with Planning and Shipping)

| Metric | Target to expand | How measured |
| --- | --- | --- |
| Past-due quantity matches manual (after explaining timing differences) | ≥ 98% of lines exact; 100% of differences explained | Daily reconciliation file |
| Missed Critical / Past Due exceptions | 0 in the 10-day parallel run | Shipping log vs. `SZW_Exceptions` |
| False alert rate | ≤ 10% of alerts | Owner reason codes |
| Scheduled runs completed and alerts delivered | ≥ 99% | `SZW_RunLog` |
| Time from data change to alert | ≤ 75 min during business hours | Export timestamp vs. LastNotified |
| Manual backlog reporting time | ≥ 70% reduction | Planner time estimate before vs. after |

## 10. Expansion roadmap

Scope grows by adding configuration rows and data sources, not by rebuilding the flows. Each phase starts only after the previous phase's gate is met.

| Phase | Adds | Architecture change | Entry gate |
| --- | --- | --- | --- |
| 1 Pilot (Nov–Dec 2026) | SZW requirements, shipments, FG netting, alerts, daily/weekly reports | SharePoint files + lists, one semantic model, five flows | — |
| 2 Predictive (Q1 2027) | Work orders/WIP, scheduled completions, quality holds, material shortages, R6 rule, days-to-shortage | Supply table + time-phased netting. Snapshots move to a Fabric Lakehouse table | Pilot acceptance criteria met |
| 3a Next 2–3 customers (Q2 2027) | Customer-specific ship-date rules, transit days, priority | `CustomerRules` config table; RLS by customer group; one exception channel per value stream | Phase 2 status matches planner judgment ≥ 90% for 4 weeks |
| 3b All customers and plants | Plant dimension, company-wide view, department-specific routing | Lakehouse + Dataflow Gen2 or pipelines replace file loads; SQL view / gateway instead of exports where available | 3a stable for 1 month; IT agrees on support ownership |
| 3c AI layer | NL Q&A, recovery suggestions, late-risk model | Copilot / Fabric data agent on the model; risk model only after 6+ months of snapshots | Clean history; governance sign-off |

### Built in from the start so scale doesn't force a rebuild

- Customer, plant and rule thresholds are config rows, never hard-coded in DAX or flows.
- All keys include Customer and (from Phase 3) Plant.
- Flows call one parameterized DAX query, not one query per customer.
- Owner routing is a lookup (`OwnerGroup` by customer + rule + plant), so adding a team is a list edit.

## 11. Risks and controls

The largest risk is a wrong alert sent with confidence, from stale, partial or mis-matched data. The controls below stop the agent from sending business alerts whenever the data is in doubt.

| Risk | Control | Detected by |
| --- | --- | --- |
| Stale or partial export | Freshness and header checks; alerts paused, one D1 alert sent instead | F1, F2, F5 |
| Duplicate requirement or shipment rows | Unique keys; newest LastChangeDate wins; shipment key dedup | Data Health page |
| Shipments that can't be tied to an order | Never credited; listed as Unmatched with qty | Data Health page, D1 |
| Release revisions read as new demand | Key on SO + line + release; revisions replace the earlier row; changes logged as R7 | Snapshot compare |
| UTC vs. Eastern date errors | As-of date from the export file name, never `TODAY()` in the Service | Unit test: run at 11 PM ET |
| Alert fatigue | Dedup key, re-notify only on worsening, digests, quiet hours, false-alert reason codes reviewed weekly | False alert rate KPI |
| Flow runs under a person who leaves | Service account owns flows, connections and the dataset; two co-owners | Quarterly access review |
| Unauthorized access to price or customer data | SharePoint site permissions limited to Ops + Planning; Power BI workspace roles; RLS from Phase 3 | Entra ID group membership |
| Silent flow failure | Run-after failure branches, 3 retries, F5 watchdog, monthly run-log review | F5 |
| Someone edits a threshold incorrectly | `SZW_Config` versioning on; edit rights for 2 named people; changes listed in the weekly report | List version history |
| Agent changes ERP data | Not possible: read-only exports; no write connectors to the ERP | Design review |

**Audit history:** archived raw exports (never overwritten), daily snapshot files, `SZW_Exceptions` with version history, and `SZW_RunLog`. Together they rebuild what the agent knew and sent at any hour. Proposed retention: 2 years for snapshots and the exception register, 90 days for raw hourly exports, with the last export of each day kept 2 years.

## 12. Example outputs

All parts, orders and quantities below are fictional. They were run through the section 5 formulas with an as-of date of Tue, Oct 27, 2026.

### Backlog and risk report (excerpt)

| Part | SO / line / rel | Ship date | Req qty | Open qty | FG avail | Short qty | Days past due | Aging | Status | Past-due $ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SZ-4410 | 73950 / 3 / 09 | Oct 9 | 120 | 80 | 0 | 80 | 18 | 15+ | Past Due | $568 |
| WF-3150 | 74098 / 1 / 22 | Oct 20 | 300 | 300 | 0 | 300 | 7 | 3–7 | Past Due | $3,720 |
| SZ-1001 | 74120 / 1 / 14 | Oct 26 | 500 | 150 | 200 | 0 | 1 | 1–2 | Past Due | $728 |
| WF-5025 | 74140 / 1 / 03 | Oct 27 | 400 | 400 | 900 | 0 | — | — | On Track (due today) | — |
| SZ-2002 | 74133 / 2 / 07 | Oct 28 | 1,000 | 1,000 | 600 | 400 | — | — | Critical | — |
| SZ-1001 | 74120 / 1 / 15 | Oct 30 | 500 | 500 | 200 | 450 | — | — | At Risk | — |

How to read SZ-1001: 350 units shipped on SO line 74120/1 are credited to release 14 first (cumulative method), leaving 150 past due. The 200 FG on hand covers those 150 first, so the past-due line shows no shortage and can ship today. Release 15 is then 450 short.

SZ-2002 is short 400 in Phase 1 (FG only). In Phase 2, the 200 units scheduled to finish before the shipping cutoff bring the projected shortage to 200, matching Example 2 in the brief. The brief's Example 2 says "At Risk" status with "Critical" severity; this design uses one field and labels it **Critical**, because the line is short within 1 workday.

### Daily alert (Teams, 7:00 AM digest for Planning)

> **Sub-Zero/Wolf — 3 new exceptions (Tue Oct 27, data as of 6:00 AM)**
>
> &#91;CRITICAL · R3\] SZ-1001 — SO 74120/1 rel 14 is past due by 150 units (1 day). FG available now: 200. Review recovery shipment today. *Open exception* · *View part*
>
> &#91;CRITICAL · R2\] SZ-2002 — projected 400-unit shortage for the Oct 28 shipment (1,000 required, 600 available). No recovery plan recorded. Review production recovery options and notify the responsible planner.
>
> &#91;WARNING · R1\] SZ-1001 — rel 15 due Oct 30 is projected 450 short after past-due recovery.

### Backlog-growth alert (Example 3 from the brief)

> &#91;WARNING · R4\] Sub-Zero/Wolf past-due backlog is 2,600 units, up 30% (+600 units) since the previous snapshot (2,000). Top contributors: WF-3150 (+300), SZ-1001 (+150), SZ-4410 (+80). Recommended: review overdue requirements and agree on part-level recovery plans at the 9 AM meeting.

### Executive summary (Monday weekly report)

> **Sub-Zero/Wolf — week of Oct 19–23.** On-time shipment rate 91.4% of lines (target 98%). Past-due backlog rose from 2,000 to 2,600 units ($18.9k at sell price). The three new past-due parts, WF-3150, SZ-1001 and SZ-4410, account for 530 units. Shipped 41,200 units against 43,000 required (96%). 4 Critical exceptions were opened and 3 were closed with recovery shipments. The 1 still open (SZ-4410, 18 days) is escalated to Operations. Next 7 days: 2 requirements At Risk or Critical, 850 units projected short. Most urgent is SZ-2002 on Oct 28.

The weekly figures above are illustrative, except the requirement-level numbers taken from the table.

## 13. Initial development backlog

Do the first five items this week. Everything after them depends on real export files.

| # | Task | Acceptance criteria | Owner (proposed) |
| --- | --- | --- | --- |
| 1 | Confirm the SZW customer codes and list every active SZW part | Signed-off list in `SZW_Config`; part count matches the planner's list | Daniel + Planning |
| 2 | Build the ERP **OpenOrders** export (fields in section 3) and schedule it hourly to SharePoint `ERP_Exports/Incoming` | 3 consecutive hourly files land with correct headers; row count matches an ERP screen check for 5 random orders | ERP admin |
| 3 | Build the **Shipments** and **FGInventory** exports, same schedule | Same as #2. Every shipment row has SO + line, or the share without them is measured | ERP admin |
| 4 | Create the SharePoint site structure: folders, lists `SZW_Config`, `SZW_Exceptions`, `SZW_RunLog`; service account; Teams channel "SZW Shipment Alerts" | Service account owns all; versioning on; 2 co-owners | Daniel + IT |
| 5 | Collect the last 10 days of the manual backlog report + matching archived ERP data (or ERP as-of reports) | Files stored in `Validation/` | Planning |
| 6 | Semantic model v0.1: Power Query loads, keys, RunInfo as-of date, Parts/Inventory relationship | Refresh succeeds in the Service; Data Health page shows counts equal to the file row counts | BI developer |
| 7 | Calculated columns + measures from section 5 | The six-row test set in section 12 gives exactly those Open, Short, Days past due and Status values | BI developer |
| 8 | Flow F1 Ingest with validation and refresh trigger | Bad-header file is rejected and alerted; good file triggers refresh; run logged | Power Automate developer |
| 9 | Historical reconciliation, 10 days | ≥ 98% line match; every difference classified | Daniel + Planning |
| 10 | Flow F2 Monitor + exception register dedup | Running F2 twice on unchanged data creates 0 new items and sends 0 messages; a worsened shortage re-notifies once | Power Automate developer |
| 11 | Flows F3 (snapshot + daily/weekly), F4 (escalation), F5 (watchdog) | Snapshot file every day; summary at 7:00 AM; an injected stale file triggers D1 within 2 h | Power Automate developer |
| 12 | Report pages 1–6 | Planner can answer business questions 1–10 from the brief without leaving the report | BI developer |
| 13 | Run book: what to do when an alert or a flow fails, who owns what | 1-page doc reviewed by Planning, Shipping, IT | Daniel |
| 14 | Parallel run and go/no-go | Section 9 acceptance criteria met or a dated fix list | Daniel + Ops manager |
| 15 | Optional: AI narrative step in F3 | Over 10 days, every number in the narrative matches the table; no invented parts | Power Automate developer |

### Build status (Oct 27, 2026)

The build kit is in the output folder *SZW\_Backlog\_Agent* (start with its README). Nothing is deployed yet: every remaining step needs access to SYSPRO SQL, the Fabric workspace or SharePoint.

| Piece | Status | File |
| --- | --- | --- |
| SYSPRO read-only views + truck schedule table | Written; column names to verify with the SQL admin | `sql/01_szw_views.sql`, `sql/02_shipto_schedule.sql` |
| Agent logic (truck assignment, netting, status, exceptions, de-duplication, alerts, daily summary) | Built and tested: 4 tests pass on sample data | `engine/szw_agent.py`, `tests/` |
| Power Query sources + DAX columns and measures, with truck logic | Written to match the engine | `powerbi/` |
| SharePoint list schemas, config, routing with emails | Ready to import | `config/` |
| Flows F2–F5, standard connectors only, plus Teams card | Step-by-step specs with expressions | `power-automate/` |
| Dashboard look | Mockup in the ExcessInventoryReport style | *Mockups* folder |
| Power BI report v0.1 (Monitor, PO lines, Data health; EN/ES) | PBIP project built on the Oct 28 data. 54/54 report files pass Microsoft's PBIR schemas. DAX logic mirrors the engine with 0 differences. Not yet opened in Desktop | SZW\_Backlog\_Monitor\_PBIP.zip |

The truck rule replaces the workday windows in sections 5 and 6. A line must leave on the last truck that arrives by the order date. **Critical** = short on that ship-to's next truck. **At Risk** = short on the truck after.

**Next actions:** the SQL admin creates the views (steps 1–2), Tiffany confirms the 3 ship-to codes and date basis, and Daniel builds the model (steps 3–4) and the flows.

## 14. Information needed from you

The answers to these ten questions decide the pilot build. Everything else can be settled during the build.

**ERP and data**

1. Which ERP and version? (The `StockCode` field in your excess-inventory model suggests SYSPRO; confirm.) Can it schedule report exports to a network or SharePoint folder, or does the existing semantic model read a SQL database through an on-premises gateway?
2. How do Sub-Zero/Wolf releases reach the ERP: EDI 830/862 loaded into sales order lines, a customer portal you key in, or a spreadsheet? Is there a release number on each line?
3. Do shipments (dispatch notes, packing slips) carry the sales order and line? Is shipped quantity held per release or only per SO line?
4. Which customer codes count as "Sub-Zero/Wolf" (all plants and ship-to locations)?
5. Is the date on the order the required **ship** date or the **delivery** date? If delivery, what are the transit days per ship-to?

**Current process**

6. Who keeps the manual backlog report today, how often, and in what format? Can you share 10 recent days for validation?

**Platform**

7. Is the workspace behind the shared Fabric link on Fabric/Premium capacity or Pro? Can the new model live in that workspace, and who administers it?
8. Are you allowed a service account for flows, and are premium Power Automate connectors licensed?

**Notifications**

9. Who are the named owners for Planning, Shipping, Operations, Supply chain and management escalation? Teams channel, chat or email for each?
10. Business hours and shipping cutoff time (and do you ship Saturdays)? These set the hourly window, quiet hours and the Critical window.

### Answers received (Oct 27, 2026) and what they change

| Topic | Answer | Change to the plan |
| --- | --- | --- |
| ERP and data access | SYSPRO. Power BI already reads it over SQL through the existing semantic model (the shared Fabric link) | Read SYSPRO sales order, dispatch/shipment and warehouse tables over SQL through the same gateway, not CSV exports. Flow F1 (file ingest) is dropped and replaced by a scheduled refresh. CSV stays only as a fallback |
| How releases arrive | Sub-Zero emails POs as PDF; a materials employee keys them into SYSPRO | No EDI. Each SO line with its date is the requirement. Demand changes (R7) are found by comparing daily snapshots. Limitation: a PO received but not yet keyed is invisible to the agent |
| Lead times | 8 weeks; painted aluminum parts 10–12 weeks, processed in the Mexico plant | The demand view runs 12 weeks out, not 30 days. The Phase 2 shortage check covers the full lead-time window |
| Shipment matching | Shipped quantity is held per release | Exact match per release. The cumulative FIFO method stays only as a fallback |
| Ship-to and trucks | 3 locations. Sub-Zero Whs 22 and 23: Tuesday truck, arrives Friday (3 days). Whs 10: loaded Thursday, ships Friday, arrives Monday (3 days). Updated Oct 28 | Each requirement is assigned to the last truck that arrives on time. Critical and At Risk count trucks, not workdays: Critical = short on the next truck, At Risk = short on the one after. New config table `ShipToSchedule` (ship-to, truck day, transit days) |
| Date on the order | Depends on the facility | Per ship-to flag in `ShipToSchedule`: ship date or delivery date. If delivery, the required ship date = departure of the truck that arrives in time |
| Manual backlog report | Robert and Ricardo | They validate the parallel run (section 9) |
| Service account and premium connectors | No and no | Flows run under Daniel's account with a co-owner. Only standard connectors (SharePoint, Teams, Outlook, Power BI). Data freshness is checked with a DAX query of the model's refresh timestamp, not the REST API |
| Saturday shipping | Possible, normally not | Business days are Mon–Fri. A Saturday shipment is still credited |
| Existing demand model | AthensDistribution semantic model, in the same workspace: DemandOnHand (QtyOnHand, QtyInTransit, deficit/surplus at week 3 and week 6), InventoryIssues (CurrentQOH, 3- and 6-week demand, weeks on hand), ExceptionList, GeneralData | Reuse it for Agent D. Its week-3 and week-6 deficits are a ready-made shortage signal for Phase 2, and ExceptionList shows how exceptions are tracked today. Building on it needs edit access; the screenshot shows Viewing mode |
| Parts made in Mexico | 9 distribution part numbers are made at MdM (Mexico) | Flag those 9 parts in the part list. They get the 10–12-week lead time and Mexico in-transit stock in the shortage check |

### Alert routing (loaded into `SZW_Config`)

| Rule | First notify | Escalate to (proposed) |
| --- | --- | --- |
| R1 Short within 48 h / next truck | Planning: Celia, JC | Brian |
| R2 Critical, no recovery plan | Planning: Celia, JC + Shipping: Tiffany | Brian |
| R3 Missed ship date | Operations: Brian + Planning + Shipping | Matt |
| R4 Backlog growth > 10% | Supply chain: Robert, Ricardo | Matt |
| R5 Critical unresolved > 24 h | Matt | — |
| R6 Future demand > supply | Planning: Celia, JC | Robert, Ricardo |
| R7 Demand change | Planning + Supply chain | — |
| D1 Data health | Daniel | — |

### Contacts

| Name | Role in the agent | Email |
| --- | --- | --- |
| Robert Randolph | Supply chain; keeps the manual backlog report | rrandolph@millsproducts.com |
| Ricardo Padron | Supply chain; keeps the manual backlog report | rpadron@millsproducts.com |
| Tiffany Wilcox | Shipping | twilcox@millsproducts.com |
| Juan Zacarias | Planning (JC) | jzacarias@millsproducts.com |
| Tonya Sledge | Materials; keys Sub-Zero POs into SYSPRO, which is where R7 demand changes come from | tsledge@millsproducts.com |
| Matt McMillin | Management escalation | mmcMillin@millsproducts.com |
| Celia | Planning | cnixon@millsproducts.com |
| Brian | Operations | bjhonson@millsproducts.com |

### Still open

- [ ] SYSPRO customer and ship-to codes for the 3 locations, and which ones use ship date vs. delivery date.
- [ ] Workspace capacity (Pro or Fabric/Premium) and its admin. On Pro, refresh every 2 hours instead of hourly.
- [ ] Business hours and the truck loading cutoff on Tuesday and Thursday.
- [ ] Teams channel, chat or email for each owner.
- [ ] Robert and Ricardo's report: how often, what format, and 10 recent days for validation.
- [ ] Is the Mexico plant's WIP in the same SYSPRO company (needed for Phase 2)?

## 15. Validation with the Oct 28 Sub-Zero delivery plan

The agent ran on the real *2026-10-28 Sub-Zero Backlog Recovery* workbook (128 PO lines, 21 parts) and reproduced its backlog numbers exactly. It also found 4,550 pcs that have already missed their truck but don't yet count as past due in the workbook.

### Reconciliation (as of Oct 28, 2026, pcs)

| Measure | Workbook | Agent | Note |
| --- | --- | --- | --- |
| Total open on Sub-Zero's PO list | 93,127 | 93,127 | Match |
| Past due by Sub-Zero due date | 17,870 | 17,870 | Match |
| … of which shipped or in transit | 13,380 | 13,380 | Match |
| … of which shipped, misapplied at Sub-Zero | 520 | 520 | Match |
| … of which not yet shipped (true backlog) | 3,970 | 3,970 | Match |
| Missed the truck: will arrive late, due date not yet passed | not shown | 4,550 | 7 lines due Oct 30 at Whs 22/23 (3,510) missed the Tue Oct 27 truck; P885785 (1,040) missed the Fri Oct 23 truck |
| Past due, agent view (missed truck) | — | 8,520 on 18 lines | 3,970 + 4,550 |
| Shipped by Mills, still open on Sub-Zero's list | — | 15,980 on 29 lines | New C1 rule: ask Sub-Zero to receive or apply |
| Critical: not ready for the next truck | — | 7,650 on 6 lines | Tue Nov 3 and Fri Oct 30 trucks |
| At risk: not ready for the truck after | — | 4,320 on 4 lines | Tue Nov 10 and Fri Nov 6 trucks |
| Raw material missing inside the 8-week lead time | — | 6,240 on 4 lines | 9054217 and 9054218, trucks Dec 4 and Dec 11 |

Sub-Zero's report shows 17,870 pcs past due, but only 3,970 are really unshipped. The C1 alert gives Tiffany, Robert and Ricardo the line-by-line list to clear the other 13,900 with Sub-Zero.

### What the plan showed about the real process

- **Demand comes from Sub-Zero's "Open Purchase Orders Subscription" export** (Order, Line, Release, Item, Whs, Open Qty, Due Date). It is the most direct demand source, and it already carries release numbers.
- **The 3 locations are Sub-Zero warehouses 10, 22 and 23.** Whs 22 and 23 ship Tuesday (90 of 96 lines with a ship date, actual or planned) for Friday due dates. Whs 10 ships Friday (20 of 28) and arrives Monday.
- **Transit is 3 days** in the plan (Tuesday to Friday), not the 2 business days noted earlier. The agent now uses 3; confirm with Tiffany.
- **Due Date is the arrival date at Sub-Zero.** Every ship-to is on a delivery-date basis.
- **Production status is a free-text note** ("Needs painted", "Needs rolled/stamp/painted", "Ready to ship", "Need raw material"). The agent reads it as readiness until SYSPRO stock is connected. 67 lines have no note; 41 of those are still open and are treated as covered (not flagged).

### Issues found in the workbook

- **Run schedule exceeds capacity.** At the plan's own hourly rates, the Oct 28 run needs 38.4 h on the 68.75 pcs/h parts (windows and glass packs) and 9.4 h of day-shift painting. The Nov 16 run needs 85.6 h on the same parts. If those parts share one line, the Nov 2 "backlog clear" date can't hold.
- **Recovery sheet:** column E shows #VALUE! for every part. Shipments after Nov 3 aren't entered, so the balance falls to −27,305 by Nov 24 even though those orders aren't late yet.
- **Partial shipments without a quantity** (P890389, P885786) are credited as shipped in full. The agent flags both as data issues.
- **Inconsistent labels:** P879091 says "misapplied at Subzero" in the note but "Shipped" in Ship Status, so it isn't counted in the 520.
- **Holidays** Nov 26–27, Dec 24–25, Dec 31 and Jan 1 are now in the agent's config. A truck that falls on a holiday leaves the business day before.

### Changes made to the agent

| Change | Where |
| --- | --- |
| Importer for the Sub-Zero Open PO sheet | `engine/import_subzero_openpo.py` |
| Ship-tos WHS-10 (Fri), WHS-22 and WHS-23 (Tue), 3-day transit, delivery-date basis | importer + `config` |
| Readiness from the production note when there is no FG stock figure | `engine/szw_agent.py` |
| New rule R8: raw material missing inside the lead time → Robert, Ricardo, Celia, JC | engine + `SZW_Routing.csv` |
| New rule C1: shipped but still open at the customer after arrival → Tiffany, Robert, Ricardo | engine + `SZW_Routing.csv` |
| Plant holidays; data notes for partial shipments with no quantity | engine + `SZW_Config.csv` |
| Run on the real plan: inputs and outputs | `agent/data_real_2026-10-28/` |

The first run sends 63 alerts because every open problem is new on day one. From the second run on, only new or worse items are sent.

### Questions this raised

- [x] Does the Thursday load for Whs 10 leave on Friday? Yes: loaded Thursday, ships Friday. The agent now shows a "ready by" date one business day before the Whs 10 truck.
- [x] Is Tuesday-to-Friday (3 days) the right transit for Whs 22 and 23? Yes, 3 days for all three warehouses.
- [x] Who exports the Sub-Zero Open PO list? Tiffany or Tonya. Automated: flow F0, described below.
- [ ] Do the 68.75 pcs/h parts share one line? If so, the run schedule needs to be spread over more days.

### Sub-Zero Open PO intake (flow F0)

When the Sub-Zero portal email reaches Tiffany or Tonya, an Outlook rule redirects it to Daniel's mailbox. Flow F0 saves the spreadsheet to SharePoint (`SZW_Agent/Incoming/SubZeroOpenPO`), refreshes the backlog model and logs the run. The hourly monitor then evaluates the new list. All steps use standard connectors and need no service account.

1. Tiffany and Tonya each add the Outlook rule: from the Sub-Zero portal sender, subject includes "Open Purchase Orders", redirect to Daniel.
2. Daniel builds F0 from `power-automate/FLOWS.md`. A duplicate redirected within 30 minutes is saved but doesn't refresh twice.
3. The model reads the newest file, finds the header row (the export starts with title lines), and matches each Sub-Zero PO line to SYSPRO by PO number and item.
4. The watchdog alerts Tiffany, Tonya and Daniel (D2) if no new list has arrived within 26 business hours.

Matching the portal list to SYSPRO adds two checks that answer the earlier "PO received but not keyed" gap:

| Rule | Fires when | Goes to |
| --- | --- | --- |
| K1 | A Sub-Zero PO line has no SYSPRO sales order line | Tonya, Tiffany → Celia, JC after 24 h |
| K2 | A SYSPRO SO line is open but no longer on Sub-Zero's list | Tonya, Tiffany → Robert, Ricardo after 72 h |
| C1 | Sub-Zero's open qty is above Mills' SYSPRO open qty after the truck should have arrived | Tiffany, Robert, Ricardo |

Once the portal list and SYSPRO are both connected, Mills' open quantity comes from SYSPRO, not the plan's manual columns.

**Still needed:**

- [ ] The Sub-Zero portal sender address and how often the subscription email arrives (sets the rule filter and the 26-hour watchdog).
- [ ] Is SYSPRO's StockCode the same as Sub-Zero's Item number (9054217, 720814…)? If not, the match needs the customer part cross-reference.
- [ ] Is the Sub-Zero PO number (P8…) stored in SYSPRO as the customer PO on the sales order?
