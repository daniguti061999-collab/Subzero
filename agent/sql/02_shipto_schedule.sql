/* =====================================================================
   02_shipto_schedule.sql — truck schedule per Sub-Zero/Wolf ship-to
   Confirmed by Daniel (Oct 28 2026), matching the Oct 28 recovery plan:
     - Sub-Zero Whs 22 and 23: Tuesday truck, arrives Friday (3 days)
     - Sub-Zero Whs 10: loaded Thursday, ships Friday, arrives Monday (3 days)
     - Sub-Zero's Due Date is the arrival date (DateBasis 'D') for all three
   ===================================================================== */

IF OBJECT_ID('rpt.SZW_ShipToSchedule') IS NULL
CREATE TABLE rpt.SZW_ShipToSchedule (
    ShipToKey           VARCHAR(60) NOT NULL PRIMARY KEY, -- must match vw_SZW_Requirements.ShipToKey
    ShipToName          VARCHAR(60) NOT NULL,
    TruckWeekday        TINYINT     NOT NULL,             -- 1 = Monday ... 7 = Sunday (ISO)
    TransitCalendarDays TINYINT     NOT NULL,             -- truck departure -> arrival, calendar days
    DateBasis           CHAR(1)     NOT NULL,             -- 'S' = order date is the ship date, 'D' = delivery date
    LoadDaysBefore      TINYINT     NOT NULL DEFAULT 0,   -- business days the truck is loaded before it leaves
    Active              BIT         NOT NULL DEFAULT 1
);
GO

-- ShipToKey must equal what vw_SZW_Requirements.ShipToKey returns for each location
-- (VERIFY how SYSPRO identifies Sub-Zero Whs 10 / 22 / 23 and map them to these keys).
INSERT INTO rpt.SZW_ShipToSchedule (ShipToKey, ShipToName, TruckWeekday, TransitCalendarDays, DateBasis, LoadDaysBefore) VALUES
  ('WHS-22', 'Sub-Zero Whs 22 (Tue truck)',                 2, 3, 'D', 0),
  ('WHS-23', 'Sub-Zero Whs 23 (Tue truck)',                 2, 3, 'D', 0),
  ('WHS-10', 'Sub-Zero Whs 10 (loaded Thu, ships Fri)',     5, 3, 'D', 1);
GO
