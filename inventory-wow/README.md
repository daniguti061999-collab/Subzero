# Variación semanal de inventario — Reporte Power BI

Responde: **¿qué movió el costo del inventario de la semana anterior a esta, y dónde?** Baja de Site → GroupedWH → Warehouse → StockCode y separa cada variación en efecto cantidad y efecto costo.

Guía completa (editable): https://claude.ai/artifact/Ap6vH5dRqDkVq97GYX1GBw · Mockup: `../mockups/Inventory_WoW_mockup.png`

| Archivo | Qué es |
| --- | --- |
| `01_Tablas_calculadas.dax` | Week Selector (desconectada), Language, Translations, parámetro de campos WoW Columns (EN/ES) |
| `02_Medidas_WoW.dax` | Todas las medidas; se pega en la vista de consultas DAX → "Actualizar modelo con los cambios" |
| `MillsTheme.json` | Tema Mills (azul #002F6C del ExcessInventoryReport) |

## Lógica

```
Δ = V1 − V0 = (Q1 − Q0)·C0  [efecto cantidad]  +  (C1 − C0)·Q1  [efecto costo]  +  otros
```

Se calcula por Warehouse × StockCode y se suma, así cuadra en cualquier nivel. Material nuevo o eliminado = todo efecto cantidad. "Otros" (valor sin cantidad, cantidades negativas) debe ser ~0. Probado con 6 casos; siempre suma exactamente la variación.

## Pendiente

- **Nombres reales del modelo de inventario.** Los scripts suponen `InventorySnapshot[SnapshotDate, Site, GroupedWH, Warehouse, StockCode, QtyOnHand, ExtendedCost]`. Hay que reemplazarlos con Buscar/Reemplazar.
- **Slicer de semana** sobre `Week Selector[SnapshotDate]`, nunca sobre la fecha de la tabla de snapshots.
- **Convención de color:** aumento rojo, disminución verde; se cambia en *WoW Delta Color*.
