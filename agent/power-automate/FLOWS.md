# Power Automate flows — Sub-Zero/Wolf Backlog Agent

Constraints from Daniel (Oct 27, 2026): no service account and no premium connectors.
All flows below use **standard connectors only**: Schedule, Power BI, SharePoint, Microsoft Teams, Office 365 Outlook, Data Operations.
Owner: Daniel's account. Add a co-owner (for example Juan Zacarias) so the flows survive absences.

SharePoint site layout (create once):

| Object | Type | Source |
| --- | --- | --- |
| `SZW_Exceptions` | List | Columns in `../config/SZW_Exceptions_list_schema.csv` |
| `SZW_Routing` | List | Import `../config/SZW_Routing.csv` (Lists → New → From CSV) |
| `SZW_Config` | List | Import `../config/SZW_Config.csv` |
| `SZW_RunLog` | List | Title, RunID, Flow, StartedAt, Rows, New, Updated, Cleared, Status, Error |
| `SZW_Agent/Snapshots` | Folder | Written by F3, read by the model's `BacklogSnapshot` query |
| `SZW_Agent/Incoming/SubZeroOpenPO` | Folder | Written by F0, read by the model's `SubZeroOpenPO` query (`../powerbi/03_SubZero_OpenPO.pq_and_dax.txt`) |

Status → rule mapping (same as the engine): Past Due → R3 Critical · Critical → R2 Critical · At Risk → R1 Warning · Data Issue → D1 System.
Other rules: C1 shipped but still open at Sub-Zero · K1 Sub-Zero PO not keyed in SYSPRO · K2 open in SYSPRO, not on Sub-Zero's list · R8 raw material inside lead time · D2 Sub-Zero file not received.

---

## F0 Sub-Zero Open PO intake — on each email

Tiffany Wilcox or Tonya Sledge receives the Sub-Zero portal export ("SubZero Open Purchase Orders", Vendor 007087-MILLS PRODUCTS INC).
With no service account, the flow runs on Daniel's mailbox and the file reaches it by an Outlook rule.

**One-time setup (5 minutes each, Tiffany and Tonya):** Outlook → Settings → Mail → Rules → Add new rule
- Name: `Sub-Zero Open PO to backlog agent`
- Condition: *From* = the Sub-Zero portal sender (TODO: confirm the address from one of their emails), and *Subject includes* `Open Purchase Orders`
- Action: *Redirect to* `dgutierrez@millsproducts.com` (redirect keeps the original sender and the attachment)
- Keep "Stop processing more rules" off so their own copy stays in their Inbox.

Better long-term: ask Sub-Zero to add a team address (for example a shared mailbox `szw-backlog@millsproducts.com`) to the portal subscription, then switch the trigger to **When a new email arrives in a shared mailbox (V2)**, which is also a standard connector. That removes the dependency on personal mailboxes.

**Trigger:** Office 365 Outlook → **When a new email arrives (V3)**
- Folder: Inbox · Include Attachments: **Yes** · Only with Attachments: **Yes**
- Subject Filter: `Open Purchase Orders`
- Trigger condition (Settings → Trigger conditions), so only Tiffany's, Tonya's or the portal's emails start it:
  `@or(contains(toLower(triggerOutputs()?['body/from']),'twilcox@millsproducts.com'), contains(toLower(triggerOutputs()?['body/from']),'tsledge@millsproducts.com'), contains(toLower(triggerOutputs()?['body/from']),'subzero.com'))`

**Steps**
1. **Filter array** `Sheets` — From `triggerOutputs()?['body/attachments']`, where
   `or(endsWith(toLower(item()?['name']),'.xlsx'), endsWith(toLower(item()?['name']),'.csv'))` is equal to `true`.
2. **Condition** `empty(body('Sheets'))` → Yes: post a D2 card to Daniel ("Sub-Zero email without a spreadsheet: @{triggerOutputs()?['body/subject']}") and **Terminate**.
3. **Get files (properties only)** — library Shared Documents, folder `SZW_Agent/Incoming/SubZeroOpenPO`, Filter Query
   `Created ge '@{addMinutes(utcNow(), -30)}'` — used to skip a duplicate when both Tiffany and Tonya redirect the same email.
4. **Apply to each** `Each_sheet` over `body('Sheets')`:
   **Create file** — Site `<OpsSite>`, Folder `/Shared Documents/SZW_Agent/Incoming/SubZeroOpenPO`,
   File name `concat('SubZeroOpenPO_', formatDateTime(convertFromUtc(triggerOutputs()?['body/receivedDateTime'],'Eastern Standard Time'),'yyyy-MM-dd_HHmm'), '_', items('Each_sheet')?['name'])`,
   File content `base64ToBinary(items('Each_sheet')?['contentBytes'])`.
   (The model always reads the newest file, so a duplicate does no harm; it is kept for the audit trail.)
5. **Condition** `empty(body('Get_files_(properties_only)')?['value'])` → Yes: Power BI → **Refresh a dataset** (SZW backlog model).
   No: skip the refresh, because a file arrived in the last 30 minutes and its refresh is already running.
6. **Create item** in `SZW_RunLog`: Flow = F0, file name, sender, size, Status = Received.
7. **Post message in a chat or channel** (Flow bot → channel `SZW Shipment Alerts`):
   "Sub-Zero open PO list received @{formatDateTime(convertFromUtc(utcNow(),'Eastern Standard Time'),'ddd MMM d h:mm tt')} from @{triggerOutputs()?['body/from']}. Backlog refresh started."
8. Scope `Try` / `Catch` as in F2: on failure, email Daniel the run link.

The next F2 run (hourly at :15) evaluates the new list. K1, K2 and C1 alerts go to Tonya and Tiffany as set in `SZW_Routing`.

**Watchdog (added to F5):** if the newest file in `SZW_Agent/Incoming/SubZeroOpenPO` is older than `OpenPOMaxAgeHours` in `SZW_Config` (default 26 hours on business days), post a D2 alert to Tiffany, Tonya and Daniel: "No Sub-Zero open PO list since <time>; the backlog is running on old customer data."

## F2 Monitor — hourly

**Trigger:** Recurrence. Frequency Week; days Mon–Fri; hours 6–18; minute 15; time zone (UTC-05:00) Eastern Time.

1. **Run a query against a dataset** `Query_Fresh` — workspace and semantic model of the SZW backlog model.
   Query: `EVALUATE RunInfo`
2. **Condition** `Is_stale`:
   `greater(div(sub(ticks(utcNow()), ticks(convertToUtc(first(body('Query_Fresh')?['results'][0]['tables'][0]['rows'])?['RunInfo[RefreshedAt]'], 'Eastern Standard Time'))), 600000000), 90)`
   - **Yes:** post one D1 card to Daniel ("Data is X min old — business alerts paused"), create a `SZW_RunLog` row with Status = Stale, then **Terminate** (Succeeded).
3. **Run a query against a dataset** `Query_Exceptions` — the F2 DAX query at the bottom of `../powerbi/02_Backlog_Model.dax`.
4. **Get items** `Open_items` — list `SZW_Exceptions`, Filter Query `Status ne 'Resolved' and Status ne 'Auto-cleared'`, Top Count 5000.
5. **Get items** `Routing` — list `SZW_Routing`.
6. **Initialize variable** `SeenKeys` (Array, empty).
7. **Apply to each** `Each_exception` over `body('Query_Exceptions')?['results'][0]['tables'][0]['rows']` (Concurrency **1**).
   1. **Compose** `RuleID`:
      `if(equals(items('Each_exception')?['[Status]'],'Past Due'),'R3',if(equals(items('Each_exception')?['[Status]'],'Critical'),'R2',if(equals(items('Each_exception')?['[Status]'],'At Risk'),'R1','D1')))`
   2. **Compose** `Key`: `concat(outputs('RuleID'),'|',items('Each_exception')?['[ReqKey]'],'|',items('Each_exception')?['[ReqShipDate]'])`
   3. **Append to array variable** `SeenKeys` ← `outputs('Key')`
   4. **Filter array** `Match` — From `body('Open_items')?['value']`, where `item()?['ExceptionKey']` is equal to `outputs('Key')`.
   5. **Condition** `Is_new`: `empty(body('Match'))`
      - **Yes:** **Create item** in `SZW_Exceptions` (Title = Key, Status = New, FirstDetected = LastSeen = LastNotified = utcNow(), all quantities from the row).
        Then **Filter array** `Route` on `body('Routing')?['value']` where `RuleID` = `outputs('RuleID')`, and **Post card in a chat or channel** (Post as Flow bot, Post in Channel `SZW Shipment Alerts`), card = `teams_alert_card.json`.
        For direct chats instead of a channel: **Apply to each** over `split(first(body('Route'))?['NotifyEmails'],';')` → Post card in a chat with Flow bot, Recipient = `item()`.
      - **No:** **Update item** (Id = `first(body('Match'))?['ID']`): LastSeen = utcNow(), OpenQty, ShortQty, DaysPastDue, FGAvailable.
        **Condition** `Is_worse`: severity went up, or `greater(float(items('Each_exception')?['[ShortQty]']), mul(1.2, float(first(body('Match'))?['ShortQty'])))`
        → Yes: post the card again with "Worse since last alert" and set LastNotified.
8. **Filter array** `To_clear` — From `body('Open_items')?['value']`, where `contains(variables('SeenKeys'), item()?['ExceptionKey'])` is equal to `false`, and RuleID is R1, R2, R3 or D1.
   **Apply to each** → Update item: Status = Auto-cleared, ClearedAt = utcNow(). (No message; it shows in the daily summary.)
9. **Create item** `SZW_RunLog`: rows evaluated, new, updated, cleared.
10. **Scope error handling:** put steps 1–9 in a Scope `Try`; add a Scope `Catch` with *Configure run after → has failed / has timed out* that emails Daniel the flow run URL:
    `concat('https://make.powerautomate.com/environments/', workflow()?['tags']?['environmentName'], '/flows/', workflow()?['name'], '/runs/', workflow()?['run']?['name'])`

Retry policy on every Power BI and SharePoint action: Exponential, count 3, interval PT30S.

## F3 Snapshot and summaries — daily 6:30 AM, weekly Monday 7:30 AM

1. Recurrence daily 06:30 ET.
2. **Run a query against a dataset**:
   ```
   EVALUATE
   SELECTCOLUMNS (
       FILTER ( SUMMARIZECOLUMNS ( Requirements[StockCode], "PastDueQty", [Past Due Qty] ), [PastDueQty] > 0 ),
       "SnapshotDate", FORMAT ( MAX ( RunInfo[AsOfDate] ), "yyyy-mm-dd" ),
       "StockCode", Requirements[StockCode], "PastDueQty", [PastDueQty] )
   ```
3. **Create CSV table** from the rows → **Create file** in `SZW_Agent/Snapshots/snapshot_@{formatDateTime(convertFromUtc(utcNow(),'Eastern Standard Time'),'yyyy-MM-dd')}.csv` (the CSV header must read `SnapshotDate,StockCode,PastDueQty`; use a **Select** first to strip the `[` `]` from the column names).
4. **R4 backlog growth:** query `[Past Due Qty]` and `[Past Due Prior Snapshot]`; if `Past Due Change %` > `BacklogGrowthPct` from `SZW_Config` → create an R4 exception and notify Supply chain (Robert, Ricardo).
5. 7:00 AM: query the KPIs (Past Due Qty, Past Due $, Ships Today Qty, Critical Short Qty, At Risk Short Qty) and the top 10 exceptions; **Create HTML table**; **Send an email (V2)** to the distribution list and **Post message** to the Teams channel. Format = `../sample_output/daily_summary.md`.
6. Monday 7:30 AM: same plus OTD % and the weekly backlog trend.

## F4 Escalation — every 30 min, 6 AM–6 PM, Mon–Fri

1. **Get items** `SZW_Exceptions` with Status = New or Acknowledged and RecoveryPlan empty.
2. For each: hours open = `div(sub(ticks(utcNow()), ticks(item()?['LastNotified'])), 36000000000)`.
   If greater than `EscalateAfterHours` for its rule (from `SZW_Routing`) → post the card to `EscalateEmails`, EscalationLevel + 1, LastNotified = utcNow().
3. R5: any Critical or Past Due item open > 24 h with no RecoveryPlan → Matt McMillin.

## F5 Watchdog — every 2 hours, 24/7

Alert Daniel by email if any of these is true:
- the last `SZW_RunLog` row for F2 is older than 90 minutes during 6 AM–6 PM;
- `EVALUATE RunInfo` shows RefreshedAt older than 3 hours during business hours;
- the last two F2 runs have Status = Error.

## Refresh

Scheduled refresh of the SZW backlog model through the existing gateway, at :05 every hour 6 AM–6 PM (F2 runs at :15).
On a Pro workspace, Power BI allows about 8 scheduled refreshes a day: use 6:05, 8:05, 10:05, 12:05, 14:05, 16:05 and move F2 to every 2 hours. Confirm the workspace capacity.

## Test before go-live

1. Point the model at the sample CSVs (`../sample_data`) and compare the Status table with `../sample_output/backlog_report.csv` — same statuses and short quantities.
2. Run F2 twice in a row on unchanged data: the second run must create 0 items and post 0 cards (same test as `tests/test_szw_agent.py::test_idempotent_second_run`).
3. Rename one view column to break the refresh: F5 must email within 2 hours and F2 must post a D1 instead of business alerts.
