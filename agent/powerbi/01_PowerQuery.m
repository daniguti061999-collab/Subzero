// =====================================================================
// Sub-Zero/Wolf Backlog — Power Query (one query per block; Home > New source > Blank query > Advanced editor)
// Source: SYSPRO SQL views from ../sql, through the same on-premises gateway the
// AthensDistribution / ExcessInventory models already use.
// Replace <SQLSERVER> and <SYSPRODB> with the values in the existing models' Data source settings.
// =====================================================================

// ---- Query: SysproDb (helper, disable load) ----
let
    Source = Sql.Database("<SQLSERVER>", "<SYSPRODB>")
in
    Source

// ---- Query: Requirements ----
let
    Src   = SysproDb{[Schema = "rpt", Item = "vw_SZW_Requirements"]}[Data],
    Keep  = Table.SelectRows(Src, each [LineStatus] <> "Cancelled"),
    Typed = Table.TransformColumnTypes(Keep, {
              {"ReqKey", type text}, {"SalesOrder", type text}, {"SalesOrderLine", Int64.Type},
              {"StockCode", type text}, {"ShipToKey", type text},
              {"OrderQty", type number}, {"ShippedQty", type number}, {"OpenQty", type number},
              {"OrderLineDate", type date}, {"OrderDate", type date}, {"UnitPrice", type number}})
in
    Typed

// ---- Query: Shipments ----
let
    Src   = SysproDb{[Schema = "rpt", Item = "vw_SZW_Shipments"]}[Data],
    Typed = Table.TransformColumnTypes(Src, {{"ReqKey", type text}, {"StockCode", type text},
              {"ShipQty", type number}, {"ShipDate", type date}})
in
    Typed

// ---- Query: FGInventory ----
let
    Src   = SysproDb{[Schema = "rpt", Item = "vw_SZW_FGInventory"]}[Data],
    Typed = Table.TransformColumnTypes(Src, {{"StockCode", type text}, {"Warehouse", type text},
              {"OnHandQty", type number}, {"AllocatedQty", type number}, {"UnitCost", type number}})
in
    Typed

// ---- Query: ShipToSchedule ----
let
    Src   = SysproDb{[Schema = "rpt", Item = "SZW_ShipToSchedule"]}[Data],
    Act   = Table.SelectRows(Src, each [Active] = true),
    Typed = Table.TransformColumnTypes(Act, {{"ShipToKey", type text}, {"TruckWeekday", Int64.Type},
              {"TransitCalendarDays", Int64.Type}, {"DateBasis", type text}})
in
    Typed

// ---- Query: RunInfo (one row; as-of date in plant time from the SQL server clock) ----
let
    Q = Value.NativeQuery(SysproDb,
          "SELECT CAST(GETDATE() AS date) AS AsOfDate, GETDATE() AS RefreshedAt"),
    Typed = Table.TransformColumnTypes(Q, {{"AsOfDate", type date}, {"RefreshedAt", type datetime}})
in
    Typed

// ---- Query: BacklogSnapshot (daily files written by flow F3 to SharePoint) ----
let
    Files  = SharePoint.Files("https://millsproductstn.sharepoint.com/sites/<OpsSite>", [ApiVersion = 15]),
    Snaps  = Table.SelectRows(Files, each Text.Contains([Folder Path], "/SZW_Agent/Snapshots/") and Text.EndsWith([Name], ".csv")),
    Parsed = Table.AddColumn(Snaps, "T", each Table.PromoteHeaders(Csv.Document([Content], [Delimiter = ",", Encoding = 65001]))),
    Combined = Table.Combine(Parsed[T]),
    Typed  = Table.TransformColumnTypes(Combined, {{"SnapshotDate", type date}, {"StockCode", type text}, {"PastDueQty", type number}}, "en-US")
in
    Typed
