# Sub-Zero/Wolf Shipment & Backlog Agent — Mills Products

Monitors Sub-Zero open POs against Mills shipments and trucks. It flags missed trucks, lines not ready for the next truck, shipments Sub-Zero hasn't credited, and POs not keyed in SYSPRO, and routes each alert to its owner.

- **Start here:** `CLAUDE.md` (context, rules, commands, open questions) and `docs/BUILD_PLAN.md` (full design).
- **Agent logic + tests:** `agent/` (see `agent/README.md` for the build order).
- **Power BI monitor (PBIP):** `powerbi-monitor/` (see its README to open it in Desktop).
- **Inventory week-over-week report:** `inventory-wow/`.

Quick check:

```bash
python agent/tests/test_szw_agent.py
python powerbi-monitor/tools/dax_mirror.py agent/data_real_2026-10-28
```

Requires Python 3.10+ and `openpyxl` (importer); `jsonschema` + `referencing` for `tools/validate.py`.
