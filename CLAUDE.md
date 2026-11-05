# CLAUDE.md — Mills Products: Sub-Zero/Wolf Shipment & Backlog Agent

Project context for Claude (Cowork and Claude Code). Read this first, then `docs/BUILD_PLAN.md` for the full design.

## What this is

An autonomous shipment and backlog monitor for Mills Products. Pilot: all Sub-Zero/Wolf parts; later all customers. It reconciles Sub-Zero's open POs against Mills shipments, finds past-due and at-risk lines before trucks leave, alerts the right owner, and tracks resolution.

Owner: Daniel Gutierrez (Operational Excellence), dgutierrez@millsproducts.com. Status as of Nov 5, 2026: **design and reference engine done and validated on real data; nothing deployed yet.**

There is a second, smaller deliverable in `inventory-wow/`: a weekly inventory-cost-change Power BI report, in Spanish/English.

## Hard rules

- **Read-only.** The agent never changes SYSPRO orders, schedules, inventory or shipments.
- **`agent/engine/szw_agent.py` is the reference logic.** The DAX in `powerbi-monitor/` and `agent/powerbi/`, and the flows in `agent/power-automate/`, must give identical answers. When rules change: change the engine and its tests first, then the DAX, then run `powerbi-monitor/tools/dax_mirror.py` (must report 0 mismatches).
- **Don't invent data.** Missing readiness = "Unknown" (treated as covered, counted on Data health); missing schedule = flagged D1.
- **Real customer data** (`agent/data_real_*`, `agent/source_files/`, `powerbi-monitor/Data/`) is gitignored. Don't push it to a public remote.
- **Platform constraints:** no service account and no premium Power Automate connectors. Use only standard connectors: Outlook, SharePoint, Teams, Power BI. Flows run under Daniel's account with a co-owner. Power BI Desktop runs on Windows; the Fabric workspace is AthensDistribution.

## Business rules (confirmed with Daniel)

| Topic | Rule |
| --- | --- |
| Demand source | Sub-Zero portal "Open Purchase Orders Subscription" export (Order, Line, Release, Item, Whs, Open Qty, Due Date, Status). Tiffany or Tonya receive it by email. |
| Due Date | Arrival date at Sub-Zero (date basis D) for all ship-tos |
| Ship-tos | Sub-Zero Whs 22 and 23: Tuesday truck, arrives Friday. Whs 10: loaded Thursday, ships Friday, arrives Monday. 3 calendar days of transit for all. |
| Required ship date | Latest truck day on or before (due − 3 days); on a plant holiday, the business day before |
| Holidays | 2026-11-26, 11-27, 12-24, 12-25, 12-31, 2027-01-01 |
| Saturday | Can ship but normally doesn't; business days are Mon–Fri |
| Past due | The line missed its truck (ship date < as-of). "True backlog" = Sub-Zero due date passed and still not shipped. |
| Critical / At risk | Short on that ship-to's next truck / short on the truck after |
| Short | FG netting in ship-date order when SYSPRO stock exists; otherwise readiness from the production note: "Ready to ship" or blank = covered; "Needs …", "To build" = short; "Need raw material" = short plus the R8 rule |
| Lead times | 8 weeks; painted aluminum 10–12 weeks (Mexico plant MdM); 9 distribution part numbers are made at MdM |
| Releases | Sub-Zero POs arrive as PDF/email; Tonya keys them into SYSPRO. Shipped qty is held per release. |

### Alert rules and routing (`agent/config/SZW_Routing.csv`)

| Rule | Meaning | Notify |
| --- | --- | --- |
| R1 | At risk (short on the truck after next) | Celia, JC → Brian |
| R2 | Critical (short on the next truck), no plan | Celia, JC, Tiffany → Brian |
| R3 | Missed truck (past due) | Brian, Celia, JC, Tiffany → Matt |
| R4 | Past-due backlog grew > 10% | Robert, Ricardo → Matt |
| R5 | Critical/past due open > 24 h, no plan | Matt |
| R7 | Demand change (qty up > 15% or date pulled in) | Celia, JC, Robert, Ricardo, Tonya |
| R8 | Raw material missing inside 40 workdays | Robert, Ricardo, Celia, JC → Brian |
| C1 | Shipped by Mills, still open on Sub-Zero's list after arrival | Tiffany, Robert, Ricardo → Matt |
| K1 | Sub-Zero PO line not on a SYSPRO SO | Tonya, Tiffany → Celia, JC |
| K2 | SYSPRO SO line open, not on Sub-Zero's list | Tonya, Tiffany → Robert, Ricardo |
| D1 / D2 | Data health / Sub-Zero file not received | Daniel; D2 also Tiffany, Tonya |

People: Celia (cnixon@), Juan Zacarias "JC" (jzacarias@) — Planning · Tiffany Wilcox (twilcox@) — Shipping · Brian (bjhonson@, spelling to confirm) — Operations · Robert Randolph (rrandolph@), Ricardo Padron (rpadron@) — Supply chain; they keep the manual backlog report · Tonya Sledge (tsledge@) — Materials; keys POs into SYSPRO · Matt McMillin (mmcMillin@) — management escalation. All @millsproducts.com.

## Repo map

```
agent/
  engine/szw_agent.py            reference engine (rules, netting, status, exceptions, dedup, alerts, summary)
  engine/import_subzero_openpo.py  Sub-Zero portal sheet -> engine inputs (optional --syspro match: K1/K2/C1)
  tests/test_szw_agent.py        5 tests (truck math, statuses, exceptions/dedup, idempotent rerun, portal+SYSPRO)
  sample_data/, sample_output/   fictional test set
  data_real_2026-10-28/          real run on the Oct 28 recovery plan (gitignored)
  source_files/                  the Oct 28 workbook from Matt (gitignored)
  config/                        SZW_Config, SZW_Routing, ShipToSchedule template, SharePoint list schema
  sql/                           SYSPRO read-only views (columns tagged -- VERIFY) + truck schedule table
  powerbi/                       Power Query + DAX for the production model (01, 02, 03 = Sub-Zero portal + SYSPRO match)
  power-automate/FLOWS.md        F0 intake, F2 monitor, F3 summaries, F4 escalation, F5 watchdog; Teams card JSON
powerbi-monitor/                 PBIP project (TMDL model + PBIR report, 3 pages, EN/ES) on the Oct 28 data
  tools/                         build_model.py, build_report.py, validate.py (PBIR schemas), dax_mirror.py
inventory-wow/                   weekly inventory cost change: DAX, tables, theme (Spanish)
mockups/                         PNG mockups for both dashboards
docs/BUILD_PLAN.md               full design (exported from the Claude Docs build plan)
```

## Commands

```bash
python agent/tests/test_szw_agent.py                                  # all tests must pass
cd agent/engine
python import_subzero_openpo.py "../source_files/2026-10-28 Sub-Zero Backlog Recovery - Mills Products.xlsx" --out ../data_real_2026-10-28/input
python szw_agent.py --data ../data_real_2026-10-28/input --out ../data_real_2026-10-28/output --as-of 2026-10-28
cd ../../powerbi-monitor
python tools/dax_mirror.py ../agent/data_real_2026-10-28              # must print "Mismatch lines vs engine: 0"
python tools/validate.py .                                             # PBIR JSON vs Microsoft schemas (needs github raw access)
```

Expected Oct 28 numbers: 128 PO lines; Sub-Zero open 93,127; Sub-Zero past due 17,870; true backlog 3,970; missed truck 8,520 (18 lines); critical 7,650 (6); at risk 4,320 (4); shipped not credited 15,980 (29); raw material risk 6,240 (4); readiness unknown 41 lines.

Rebuild the PBIP after changing the generators (run from `powerbi-monitor/`):

```bash
rm -rf SZW_Backlog_Monitor.SemanticModel SZW_Backlog_Monitor.Report
python tools/build_model.py .
python tools/build_report.py . tools/MillsLogo.png ../inventory-wow/MillsTheme.json
python tools/validate.py .
```

## Open questions (blocking deployment)

1. Sub-Zero portal sender address and how often the email arrives (F0 filter, D2 watchdog). Email to Tiffany and Tonya drafted Oct 28.
2. Is SYSPRO StockCode = Sub-Zero Item (9054217, 720814…)? If not, use the customer part cross-reference.
3. Is the Sub-Zero PO (P8…) stored as the customer PO on the SYSPRO SO?
4. SYSPRO column names in `agent/sql/01_szw_views.sql` (`-- VERIFY`), how Whs 10/22/23 appear in SYSPRO, and the quality-hold warehouse code (assumed `QH`).
5. Workspace capacity (Pro vs Fabric/Premium) → hourly or 2-hourly refresh.
6. Do the 68.75 pcs/h parts (windows, glass packs) share one line? The plan's run schedule needs 38 h on Oct 28 and 86 h on Nov 16.
7. Inventory WoW: real table and column names of the inventory semantic model.

## Next steps

1. Open `powerbi-monitor/SZW_Backlog_Monitor.pbip` in Power BI Desktop and fix anything Desktop reports. The TMDL has not been opened in Desktop yet.
2. Build F0 (Sub-Zero email → SharePoint → refresh). Claude can't reach Power Automate directly. Options: Copilot "describe it to design it", an import package, or the Dataverse MCP / `pac` CLI from a linked computer.
3. SQL admin creates the views; switch the model partitions from CSV to SQL/SharePoint (see `powerbi-monitor/README.md`).
4. 10-day parallel run against Robert and Ricardo's report; go/no-go.

## Links

- Build plan (living doc): https://claude.ai/artifact/JEcP4tkdMin1q7tgr834oJ
- Inventory WoW guide: https://claude.ai/artifact/Ap6vH5dRqDkVq97GYX1GBw
- Existing models: AthensDistribution (DemandOnHand, InventoryIssues, ExceptionList, GeneralData) and ExcessInventoryReport (style reference: navy #002F6C header, white Mills logo, footer #DBE2E9)
