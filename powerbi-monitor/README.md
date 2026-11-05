# SZW Backlog Monitor — Power BI project (v0.1)

A Power BI Project (PBIP) of the Sub-Zero/Wolf Shipment & Backlog Monitor mockup. The semantic model computes the agent's rules in DAX (truck assignment, readiness, past due, critical, at risk, shipped-not-credited). It loads the real Oct 28 Sub-Zero data, which is included in `Data/`.

## Open it (Power BI Desktop, Windows)

1. Copy this whole folder to `C:\SZW_Backlog_Monitor\`, so the data sits in `C:\SZW_Backlog_Monitor\Data\`.
2. Power BI Desktop → File → Options → Preview features: turn on **Power BI Project (.pbip) save option**, **Store semantic model using TMDL format** and **Store reports using enhanced metadata format (PBIR)** (if your version still lists them as preview). Restart Desktop.
3. Open `SZW_Backlog_Monitor.pbip`.
4. If the folder is somewhere else: Transform data → Edit parameters → `DataFolder` = the full path to `Data\`, with the trailing backslash.
5. **Refresh**. The Data health page should show **Mismatch lines = 0**.
6. Publish to the AthensDistribution workspace (or wherever the backlog model will live).

`AsOfOverride` is set to `2026-10-28` so the numbers match the Oct 28 plan. Clear it, so it's empty, to use today's date.

## What you should see after refresh (Oct 28 data)

| Card | Value |
| --- | --- |
| Past due: missed the truck | 8,520 (18 lines) |
| True backlog: due date passed, not shipped | 3,970 (Sub-Zero shows 17,870) |
| Critical: not ready for the next truck | 7,650 (6 lines) |
| At risk: not ready for the truck after | 4,320 (4 lines) |
| Shipped, still open at Sub-Zero | 15,980 (29 lines) |

These are the agent engine's numbers. Before packaging, the DAX logic was checked line by line against them with `tools/dax_mirror.py`: 0 differences.

## Pages

- **Monitor:** Mills header with ship-to, part and status slicers and the EN | ES switch; 5 KPI cards; next trucks; past due by part and age; daily trend; open exceptions with owners.
- **PO lines:** every Sub-Zero PO line with truck date, ready-by date, Sub-Zero vs. Mills open qty, short qty, readiness and the plan notes.
- **Data health:** model vs. agent engine by status, lines that differ, lines with no production note, raw-material risk.

## Moving to production sources

| Table | v0.1 source (`Data\`) | Production source |
| --- | --- | --- |
| Requirements | `input\requirements.csv` | Sub-Zero Open PO file from flow F0 + SYSPRO views (`SZW_Backlog_Agent/powerbi/03_SubZero_OpenPO.pq_and_dax.txt`) |
| Shipments, FGInventory | `input\*.csv` | `rpt.vw_SZW_Shipments`, `rpt.vw_SZW_FGInventory` via the gateway |
| ShipToSchedule, Holidays | `input\*.csv` | `rpt.SZW_ShipToSchedule`, `SZW_Config` list |
| Exceptions | `output\exceptions_register.csv` | SharePoint list `SZW_Exceptions` (flows F2/F4) |
| BacklogSnapshot | `output\snapshot_*.csv` | SharePoint folder `SZW_Agent/Snapshots` (flow F3) |
| EngineCheck | `output\backlog_report.csv` | Keep during the parallel run, then remove |

Only the Power Query partitions change. The DAX columns, measures and report stay as they are.

## If Desktop reports an error on open

The JSON files were validated against Microsoft's published PBIR schemas (54 of 54 pass). The TMDL can only be checked by Desktop itself. If it reports a line, send me the message. `tools/build_model.py` and `tools/build_report.py` regenerate the whole project after a fix.

Known v0.1 limits:
- Today's date uses Eastern Standard Time (UTC−5) all year.
- The EN | ES switch translates titles and card labels, not table column headers.
- The quality-hold warehouse code is assumed to be `QH`.
