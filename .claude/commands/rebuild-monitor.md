---
description: Regenerate and validate the SZW Backlog Monitor PBIP from its generators
---
From `powerbi-monitor/`:
1. `rm -rf SZW_Backlog_Monitor.SemanticModel SZW_Backlog_Monitor.Report`
2. `python tools/build_model.py .`
3. `python tools/build_report.py . tools/MillsLogo.png ../inventory-wow/MillsTheme.json`
4. `python tools/validate.py .` (every file must print `ok`)
5. Run /check-sync.
Report what changed. Remind Daniel that the TMDL is only fully checked when Power BI Desktop opens the .pbip.
