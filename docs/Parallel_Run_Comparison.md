# Sub-Zero Backlog Agent — 10-Day Parallel Run Guide

Owner: Daniel Gutierrez · Start date: TBD · Go/no-go by: TBD + 10 business days

---

## Purpose

Run the agent alongside Robert Randolph and Ricardo Padron's manual backlog report
for 10 consecutive business days.  At the end, compare the two line by line.
Discrepancies either reveal a data gap in the agent (fix it) or reveal an error in
the manual report (document it).  A "go" decision requires ≤ 5 % discrepancy on
past-due units and zero missed Critical or Past-Due lines.

---

## Who does what

| Role | Person | Task |
|---|---|---|
| Agent runs | Daniel | Run `/run-agent` each morning before 8 AM ET |
| Manual report | Robert, Ricardo | Send the daily Excel snapshot to Daniel by 9 AM ET |
| Comparison | Daniel (or Claude) | Fill the comparison log (see below) |
| Go/no-go decision | Matt McMillin | After day 10 |

---

## Comparison log — one row per day

Save as `docs/parallel_run_log.csv`.

```
Date,AgentPastDueUnits,ManualPastDueUnits,Delta_pct,AgentCriticalLines,ManualCriticalLines,AgentAtRiskLines,ManualAtRiskLines,MissedByAgent,MissedByManual,Notes
2026-10-28,8520,,,,,,,,,"Baseline — agent only"
```

**Column definitions**

| Column | Source |
|---|---|
| `AgentPastDueUnits` | `daily_summary.md` → "Past-due backlog: X units" |
| `ManualPastDueUnits` | Robert/Ricardo's report total past-due units |
| `Delta_pct` | `abs(Agent − Manual) / Manual` — target < 5 % |
| `AgentCriticalLines` | `daily_summary.md` → "Critical … 6 lines" |
| `ManualCriticalLines` | Manual report critical count |
| `MissedByAgent` | Lines in manual report NOT in agent's backlog_report.csv |
| `MissedByManual` | Lines in agent's Past Due / Critical NOT in manual report |

---

## Line-level comparison (run on each day's output)

```python
# Run from szw-backlog-agent/ after each /run-agent call
# Requires: pandas  (pip install pandas)
import pandas as pd, sys

date = sys.argv[1]            # e.g. 2026-11-06
manual_path = sys.argv[2]     # path to Robert/Ricardo's Excel

agent = pd.read_csv(f"agent/data_real_{date}/output/backlog_report.csv")
manual = pd.read_excel(manual_path)

# Rename manual columns to match agent — update these once you see the manual report:
# manual = manual.rename(columns={"PO": "CustomerPoNumber", "Part": "StockCode", ...})

agent_past_due   = agent[agent["Status"].isin(["Past Due","Critical"])]
# manual_past_due = manual[manual["Status"] == "Past Due"]  # adjust column name

# Lines agent sees but manual doesn't
only_agent = agent_past_due[~agent_past_due["ReqKey"].isin(manual_past_due["ReqKey"])]
# Lines manual sees but agent doesn't
only_manual = manual_past_due[~manual_past_due["ReqKey"].isin(agent_past_due["ReqKey"])]

print(f"Only in agent ({len(only_agent)} lines):")
print(only_agent[["StockCode","CustomerPoNumber","ReqShipDate","OpenQty","Status"]])
print(f"\nOnly in manual ({len(only_manual)} lines):")
print(only_manual)
```

---

## Go/no-go criteria

| Metric | Go | No-go |
|---|---|---|
| Past-due unit delta (10-day avg) | < 5 % | ≥ 5 % |
| Critical/Past-Due lines missed by agent | 0 | ≥ 1 |
| Data health alerts (D1) per day | ≤ 1 | ≥ 2 consecutive |
| False-positive alerts (Critical lines that weren't) | ≤ 2 total | > 2 |

---

## Open items before starting

1. Robert/Ricardo: confirm the column names in the manual report so the comparison script can be completed.
2. Confirm the Sub-Zero portal sends the open PO list daily (or on demand) — sets the agent's data freshness.
3. Confirm SYSPRO SO customer codes for Sub-Zero (open question #2 in CLAUDE.md) so the SQL views return real data for the parallel run.
