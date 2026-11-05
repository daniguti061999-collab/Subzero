---
description: Import a Sub-Zero Open PO workbook and run the backlog agent for a date
argument-hint: <path to xlsx> <as-of yyyy-mm-dd>
---
Run the Sub-Zero/Wolf backlog agent on $ARGUMENTS.

1. Run `python agent/tests/test_szw_agent.py`. Stop if anything fails.
2. With the workbook path and as-of date from the arguments (default: newest file in `agent/source_files/`, today's date), create `agent/data_real_<as-of>/` and run:
   - `python agent/engine/import_subzero_openpo.py "<xlsx>" --out agent/data_real_<as-of>/input`
   - `python agent/engine/szw_agent.py --data agent/data_real_<as-of>/input --out agent/data_real_<as-of>/output --as-of <as-of>`
3. Summarize `output/daily_summary.md`: past due (missed truck), true backlog, critical, at risk, shipped-not-credited, raw-material risk. Compare with the previous run folder if there is one.
4. Never modify SYSPRO or any source workbook.
