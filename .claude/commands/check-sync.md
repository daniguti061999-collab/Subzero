---
description: Check that the Power BI DAX logic still matches the reference engine
---
1. Run `python agent/tests/test_szw_agent.py`.
2. Run `python powerbi-monitor/tools/dax_mirror.py agent/data_real_2026-10-28` (or the newest `agent/data_real_*` folder). It must print `Mismatch lines vs engine: 0`.
3. If anything differs: the engine (`agent/engine/szw_agent.py`) is the source of truth. Explain which calculated column in `powerbi-monitor/tools/build_model.py` diverges, fix the generator and `tools/dax_mirror.py` together, and rerun until 0.
