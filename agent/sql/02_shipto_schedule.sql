/* =====================================================================
   Mills Products — Sub-Zero/Wolf Backlog Agent
   02_shipto_schedule.sql  (SQL Server, SYSPRO company database)

   Persistent table for the truck schedule.  Create this BEFORE the views
   in 01_szw_views.sql, then import the rows from ShipToSchedule_template.csv
   (or insert them manually below).

   Columns match the Power Query source in powerbi/01_ShipToSchedule.pq
   and the Python engine's input/shipto_schedule.csv.
   ===================================================================== */

IF SCHEMA_ID('rpt') IS NULL EXEC('CREATE SCHEMA rpt');
GO

-- Drop and re-create so the script is idempotent
IF OBJECT_ID('rpt.SZW_ShipToSchedule') IS NOT NULL DROP TABLE rpt.SZW_ShipToSchedule;
GO

CREATE TABLE rpt.SZW_ShipToSchedule (
    ShipToKey            VARCHAR(30)  NOT NULL PRIMARY KEY,
    ShipToName           VARCHAR(100) NOT NULL,
    -- Day the truck leaves Mills (ISO weekday: 1=Mon … 7=Sun)
    TruckWeekday         TINYINT      NOT NULL CHECK (TruckWeekday BETWEEN 1 AND 7),
    -- Calendar days of transit (3 for all Sub-Zero warehouses)
    TransitCalendarDays  TINYINT      NOT NULL,
    -- Date basis used by Sub-Zero on the PO: 'D' = delivery/arrival date
    DateBasis            CHAR(1)      NOT NULL DEFAULT 'D',
    -- Extra lead days to load before the truck day (Whs 10 is loaded Thu, departs Fri → LoadDaysBefore = 1)
    LoadDaysBefore       TINYINT      NOT NULL DEFAULT 0,
    Active               BIT          NOT NULL DEFAULT 1
);
GO

-- -------------------------------------------------------------------------
-- Seed rows (from ShipToSchedule_template.csv / CLAUDE.md business rules)
-- TODO: replace ShipToKey values with the actual SYSPRO ship-to codes once
--       confirmed (open question #2 in CLAUDE.md).
-- -------------------------------------------------------------------------
INSERT INTO rpt.SZW_ShipToSchedule
    (ShipToKey, ShipToName, TruckWeekday, TransitCalendarDays, DateBasis, LoadDaysBefore, Active)
VALUES
    ('WHS-22', 'Sub-Zero Whs 22 (Tue truck)',         2, 3, 'D', 0, 1),
    ('WHS-23', 'Sub-Zero Whs 23 (Tue truck)',         2, 3, 'D', 0, 1),
    ('WHS-10', 'Sub-Zero Whs 10 (loaded Thu/Fri)',    5, 3, 'D', 1, 1);
GO

-- -------------------------------------------------------------------------
-- Verify: row count must equal 3; TruckWeekday 2 = Tuesday, 5 = Friday
-- -------------------------------------------------------------------------
SELECT ShipToKey, ShipToName, TruckWeekday, TransitCalendarDays, LoadDaysBefore, Active
FROM   rpt.SZW_ShipToSchedule
ORDER  BY ShipToKey;
