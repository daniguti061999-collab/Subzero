# Sub-Zero/Wolf Shipment & Backlog Agent — build kit

Build order (each step has its own file):

| Step | What | File | Who |
| --- | --- | --- | --- |
| 1 | Create read-only SQL views on the SYSPRO database (schema `rpt`); fill `rpt.SZW_Customers` | `sql/01_szw_views.sql` | SYSPRO / SQL admin |
| 2 | Create the truck schedule table and load the 3 ship-tos | `sql/02_shipto_schedule.sql` | SQL admin + Shipping (Tiffany) |
| 3 | New semantic model in the Fabric workspace: Power Query sources | `powerbi/01_PowerQuery.m` | Daniel |
| 4 | Calculated columns + measures; run the check query | `powerbi/02_Backlog_Model.dax` | Daniel |
| 5 | SharePoint lists from the CSVs | `config/*.csv` | Daniel |
| 6 | Flow F0: Sub-Zero Open PO email → SharePoint → refresh (Outlook rule by Tiffany and Tonya) | `power-automate/FLOWS.md` (F0) | Daniel, Tiffany, Tonya |
| 6b | Sub-Zero Open PO query + matching to SYSPRO (K1, K2, C1) | `powerbi/03_SubZero_OpenPO.pq_and_dax.txt` | Daniel |
| 6c | Flows F2–F5 (standard connectors only) + Teams card | `power-automate/FLOWS.md`, `teams_alert_card.json` | Daniel + co-owner |
| 7 | Report pages (see the mockup) | `../mockups/SZW_Backlog_Monitor_mockup.png` and `../powerbi-monitor/` | Daniel |
| 8 | Parallel run vs. Robert and Ricardo's report | `engine/szw_agent.py` | Daniel, Robert, Ricardo |

## Reference engine

`engine/szw_agent.py` holds the agent's full logic (truck assignment, netting, status, exceptions, de-duplication, alerts, daily summary). The DAX and the flows must give the same answers.

```
python engine/szw_agent.py --data sample_data --out sample_output --as-of 2026-10-27
python tests/test_szw_agent.py
```

To run it on real data, export the three SQL views to CSV (`requirements.csv`, `shipments.csv`, `fg_inventory.csv`), add `shipto_schedule.csv`, `SZW_Config.csv`, `SZW_Routing.csv`, and point `--data` at that folder. It only reads and writes files; it never changes SYSPRO.

Everything in `sample_data` is fictional.

## Real data: Sub-Zero Open PO list

```
python engine/import_subzero_openpo.py "source_files/2026-10-28 Sub-Zero Backlog Recovery - Mills Products.xlsx" --out data_real_2026-10-28/input
python engine/szw_agent.py --data data_real_2026-10-28/input --out data_real_2026-10-28/output --as-of 2026-10-28
```

With a SYSPRO extract of `rpt.vw_SZW_Requirements`, add `--syspro syspro_requirements.csv`. Mills' open qty then comes from SYSPRO, and the run also flags Sub-Zero POs not keyed in SYSPRO (K1) and SYSPRO lines no longer on Sub-Zero's list (K2).

`data_real_2026-10-28/output` holds the Oct 28 run: 18 lines past due (8,520 pcs), 6 critical, 4 at risk, 29 lines shipped but still open at Sub-Zero (15,980 pcs).

## Assumptions to verify (tagged `-- VERIFY` in the SQL)

- SYSPRO columns: outstanding qty = `MShipQty + MBackOrderQty`; shipments from `ArTrnDetail` (switch to dispatch notes if you ship before invoicing); order status codes.
- How the 3 Sub-Zero locations are identified in SYSPRO (ship-to code, customer code or address).
- Quality-hold warehouse code (`QH` in the samples).
- Netting uses FG on hand for the part. If those parts also ship to other customers, their open orders compete for the same stock (Phase 2).
