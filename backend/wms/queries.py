"""SQL uses only columns and relationships documented in the supplied WMS map.

All values, including pagination and dates, use DB parameters. Table and column
names are static; requests cannot supply SQL identifiers.
"""

CLIENTS = """
SELECT id, name, inn, is_active FROM public.clients_client
WHERE (name ILIKE %s OR inn ILIKE %s)
ORDER BY name, id LIMIT %s OFFSET %s
"""
CLIENT = """
SELECT id, name, inn, is_active FROM public.clients_client
WHERE id = %s LIMIT 1
"""

DETAILS = {
    "stock": """
        SELECT s.product_id, p.sku, p.name, s.quantity, s.reserved_quantity,
               s.quantity - s.reserved_quantity AS available_quantity,
               s.warehouse_id, s.cell_id, s.batch_id, s.box_id, s.updated_at
        FROM public.stocks_stock s
        JOIN public.products_product p ON p.id = s.product_id
        WHERE p.client_id = %s
        ORDER BY p.sku, s.product_id, s.warehouse_id, s.cell_id,
                 s.batch_id NULLS FIRST, s.box_id NULLS FIRST
        LIMIT %s OFFSET %s
    """,
    "orders": """
        SELECT o.id, o.order_type, o.status, o.created_at, o.shipment_deadline,
               o.planned_ship_date, o.client_id, o.marketplace_id,
               o.warehouse_id, o.wave_id
        FROM public.orders_order o
        WHERE o.client_id = %s AND o.created_at >= %s AND o.created_at < %s
        ORDER BY o.created_at DESC, o.id DESC LIMIT %s OFFSET %s
    """,
    "receivings": """
        SELECT r.status, r.kind, r.received_at, r.created_at, r.confirmed_at,
               r.client_id, r.assigned_to_id, r.return_reason
        FROM public.receivings_receiving r
        WHERE r.client_id = %s AND r.created_at >= %s AND r.created_at < %s
        ORDER BY r.created_at DESC, r.status, r.kind,
                 r.assigned_to_id NULLS FIRST LIMIT %s OFFSET %s
    """,
    "shipments": """
        SELECT s.status, s.shipped_at, s.created_at, s.order_id,
               s.warehouse_id, s.tracking_number
        FROM public.shipments_shipment s
        JOIN public.orders_order o ON o.id = s.order_id
        WHERE o.client_id = %s AND s.created_at >= %s AND s.created_at < %s
        ORDER BY s.created_at DESC, s.order_id, s.tracking_number
        LIMIT %s OFFSET %s
    """,
    "movements": """
        SELECT m.movement_type, m.quantity, m.created_at, m.warehouse_id,
               m.product_id, p.sku, p.name, m.created_by_id,
               m.order_id, m.receiving_id, m.shipment_id, m.task_id,
               m.from_cell_id, m.to_cell_id, m.reversal_of_id
        FROM public.movements_movement m
        JOIN public.products_product p ON p.id = m.product_id
        WHERE p.client_id = %s AND m.created_at >= %s AND m.created_at < %s
        ORDER BY m.created_at DESC, m.product_id, m.movement_type,
                 m.quantity, m.warehouse_id LIMIT %s OFFSET %s
    """,
}

STOCK_SUMMARY = """
SELECT COALESCE(SUM(s.quantity), 0) AS total,
       COALESCE(SUM(s.reserved_quantity), 0) AS reserved
FROM public.stocks_stock s
JOIN public.products_product p ON p.id = s.product_id
WHERE p.client_id = %s
"""

DOCUMENT_SUMMARY = """
SELECT
    (SELECT COUNT(*) FROM public.orders_order
     WHERE client_id = %s AND status IN ('new', 'confirmed', 'picking', 'packed'))
        AS active_orders,
    (SELECT COUNT(*) FROM public.receivings_receiving
     WHERE client_id = %s AND status IN ('draft', 'confirmed', 'in_receiving'))
        AS active_receivings,
    (SELECT COUNT(*) FROM public.receivings_receiving
     WHERE client_id = %s AND status = 'in_receiving') AS receiving_in_progress,
    (SELECT COUNT(*) FROM public.shipments_shipment s
     JOIN public.orders_order o ON o.id = s.order_id
     WHERE o.client_id = %s AND s.status IN ('shipped', 'delivered')
       AND s.shipped_at >= %s AND s.shipped_at < %s) AS shipments
"""

MOVEMENT_SUMMARY = """
SELECT COALESCE(SUM(CASE WHEN m.movement_type = 'receiving'
                       THEN m.quantity ELSE 0 END), 0) AS received_units,
       COALESCE(SUM(CASE WHEN m.movement_type = 'shipment'
                       THEN m.quantity ELSE 0 END), 0) AS shipped_units
FROM public.movements_movement m
JOIN public.products_product p ON p.id = m.product_id
WHERE p.client_id = %s AND m.created_at >= %s AND m.created_at < %s
  AND m.reversal_of_id IS NULL
  AND m.movement_type IN ('receiving', 'shipment')
"""

BILLING_SUMMARY = """
SELECT COALESCE(SUM(amount), 0) AS billing_total
FROM lk_wms.billing_billingcharge
WHERE contractor_id = %s AND created_at >= %s AND created_at < %s
"""

ATTENTION = """
SELECT
    (SELECT COUNT(*) FROM public.tasks_task WHERE client_id = %s
     AND deadline < %s AND status NOT IN ('done', 'canceled')) AS overdue_tasks,
    (SELECT COUNT(*) FROM public.orders_order WHERE client_id = %s
     AND shipment_deadline <= %s
     AND status IN ('new', 'confirmed', 'picking', 'packed')) AS deadline_orders,
    ((SELECT COUNT(*) FROM lk_wms.orders_receivingrequest
      WHERE contractor_id = %s AND status = 'submitted' AND wms_receiving_id IS NULL)
     + (SELECT COUNT(*) FROM lk_wms.orders_shipmentrequest
        WHERE contractor_id = %s AND status = 'submitted' AND wms_order_id IS NULL))
        AS pending_requests,
    (SELECT COUNT(*) FROM public.integrations_integration WHERE client_id = %s
     AND is_active AND last_sync_status = 'error') AS integration_errors,
    (SELECT COUNT(*) FROM public.integrations_integration WHERE client_id = %s
     AND is_active AND (last_synced_at IS NULL OR last_synced_at < %s))
        AS stale_integrations
"""
