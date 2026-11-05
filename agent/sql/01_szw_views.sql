/* =====================================================================
   Mills Products — Sub-Zero/Wolf Shipment & Backlog Agent
   01_szw_views.sql  (SQL Server, SYSPRO company database)

   Read-only views for the Power BI semantic model.
   Create them in a separate schema (e.g. [rpt]) so nothing in SYSPRO tables changes.

   >>> VERIFY BEFORE RUNNING <<<
   SYSPRO column names below are the standard ones (SorMaster, SorDetail,
   ArTrnDetail, InvWarehouse, InvMaster). Check them against your SYSPRO
   version, or against the SQL query already used by the AthensDistribution /
   ExcessInventory models. Every assumption is tagged  -- VERIFY.

   Business rules (from Daniel, Oct 27 2026):
   - Each Sub-Zero release is keyed into SYSPRO as a sales order line;
     shipped quantity is held per release (= per SO line).
   - Ship-to schedule and date basis live in rpt.SZW_ShipToSchedule (02 file).
   ===================================================================== */

-- ---------------------------------------------------------------------
-- 0) Schema
-- ---------------------------------------------------------------------
IF SCHEMA_ID('rpt') IS NULL EXEC('CREATE SCHEMA rpt');
GO

-- ---------------------------------------------------------------------
-- 1) Customer list for the pilot (one row per SYSPRO customer code)
--    Add codes here instead of editing the views.
-- ---------------------------------------------------------------------
IF OBJECT_ID('rpt.SZW_Customers') IS NULL
CREATE TABLE rpt.SZW_Customers (
    Customer      VARCHAR(15)  NOT NULL PRIMARY KEY,   -- SYSPRO customer code
    CustomerGroup VARCHAR(30)  NOT NULL DEFAULT 'Sub-Zero/Wolf'
);
-- INSERT INTO rpt.SZW_Customers (Customer) VALUES ('<code1>'), ('<code2>'), ('<code3>');  -- TODO codes
GO

-- ---------------------------------------------------------------------
-- 2) Ship-to truck schedule (see 02_shipto_schedule.sql for the table)
-- ---------------------------------------------------------------------

-- ---------------------------------------------------------------------
-- 3) Requirements: one row per open (or recently completed) SO line
-- ---------------------------------------------------------------------
CREATE OR ALTER VIEW rpt.vw_SZW_Requirements AS
SELECT
    m.Customer,
    c.CustomerGroup,
    m.CustomerPoNumber,                                   -- Sub-Zero PO (from the PDF)
    m.SalesOrder,
    d.SalesOrderLine,
    CONCAT(RTRIM(m.SalesOrder), '|', d.SalesOrderLine)   AS ReqKey,
    RTRIM(d.MStockCode)                                  AS StockCode,
    d.MStockDes                                          AS StockDescription,
    d.MWarehouse                                         AS Warehouse,
    COALESCE(NULLIF(RTRIM(m.ShipAddress1), ''), m.Customer) AS ShipToKey,  -- VERIFY: how the 3 locations are identified (ship-to code, customer code or address)
    d.MOrderQty                                          AS OrderQty,
    d.MOrderQty - (d.MShipQty + d.MBackOrderQty)         AS ShippedQty,    -- VERIFY: shipped to date = ordered - outstanding
    d.MShipQty + d.MBackOrderQty                         AS OpenQty,       -- VERIFY: outstanding = ship qty + back order qty
    CAST(d.MLineShipDate AS DATE)                        AS OrderLineDate, -- the date keyed from the PO (ship OR delivery, per ship-to)
    CAST(m.OrderDate AS DATE)                            AS OrderDate,
    d.MPrice                                             AS UnitPrice,
    m.OrderStatus,
    CASE WHEN m.OrderStatus IN ('9') THEN 'Complete'                        -- VERIFY status codes
         WHEN m.OrderStatus IN ('\') THEN 'Cancelled'
         WHEN m.OrderStatus IN ('S') THEN 'Suspended'
         ELSE 'Open' END                                 AS LineStatus
FROM SorMaster m
JOIN SorDetail d        ON d.SalesOrder = m.SalesOrder
JOIN rpt.SZW_Customers c ON c.Customer  = m.Customer
WHERE d.LineType = '1'                                                     -- stocked merchandise lines only
  AND (
        (d.MShipQty + d.MBackOrderQty) > 0                                  -- open
        OR CAST(d.MLineShipDate AS DATE) >= DATEADD(DAY, -120, CAST(GETDATE() AS DATE))  -- recent, for OTD
      );
GO

-- ---------------------------------------------------------------------
-- 4) Shipments: invoiced/dispatched lines for the SZW customers, last 120 days
--    Uses ArTrnDetail (invoice = shipment). If you ship on dispatch notes
--    before invoicing, switch to MdnMaster/MdnDetail.            -- VERIFY
-- ---------------------------------------------------------------------
CREATE OR ALTER VIEW rpt.vw_SZW_Shipments AS
SELECT
    t.Invoice                                            AS ShipmentNo,
    t.DetailLine,
    t.SalesOrder,
    t.SalesOrderLine,
    CONCAT(RTRIM(t.SalesOrder), '|', t.SalesOrderLine)   AS ReqKey,
    RTRIM(t.StockCode)                                   AS StockCode,
    t.Customer,
    t.QtyInvoiced                                        AS ShipQty,        -- credit notes come through negative
    CAST(t.InvoiceDate AS DATE)                          AS ShipDate
FROM ArTrnDetail t
JOIN rpt.SZW_Customers c ON c.Customer = t.Customer
WHERE t.LineType = '1'                                                     -- VERIFY
  AND t.InvoiceDate >= DATEADD(DAY, -120, CAST(GETDATE() AS DATE));
GO

-- ---------------------------------------------------------------------
-- 5) FG inventory for the parts that appear in SZW demand
-- ---------------------------------------------------------------------
CREATE OR ALTER VIEW rpt.vw_SZW_FGInventory AS
SELECT
    RTRIM(w.StockCode)                                   AS StockCode,
    w.Warehouse,
    w.QtyOnHand                                          AS OnHandQty,
    w.QtyAllocated                                       AS AllocatedQty,
    w.QtyInTransit                                       AS InTransitQty,   -- VERIFY column exists in your version
    w.UnitCost,
    im.Description,
    im.ProductClass
FROM InvWarehouse w
JOIN InvMaster im ON im.StockCode = w.StockCode
WHERE w.StockCode IN (SELECT StockCode FROM rpt.vw_SZW_Requirements);
-- Quality-hold stock: if held in a separate warehouse (e.g. 'QH'), exclude it in the model,
-- not here, so the hold quantity stays visible.                       -- VERIFY hold warehouse code
GO

-- ---------------------------------------------------------------------
-- 6) Sanity checks — run after creating the views
-- ---------------------------------------------------------------------
-- a) Open qty per customer should match the SYSPRO back-order report
-- SELECT Customer, SUM(OpenQty) AS OpenQty FROM rpt.vw_SZW_Requirements WHERE LineStatus = 'Open' GROUP BY Customer;
-- b) Lines whose shipped qty is negative or above ordered qty (should be none)
-- SELECT * FROM rpt.vw_SZW_Requirements WHERE ShippedQty < 0 OR ShippedQty > OrderQty;
-- c) Shipments that do not match a requirement line
-- SELECT s.* FROM rpt.vw_SZW_Shipments s LEFT JOIN rpt.vw_SZW_Requirements r ON r.ReqKey = s.ReqKey WHERE r.ReqKey IS NULL;
