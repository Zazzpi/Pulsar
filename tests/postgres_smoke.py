"""Run against disposable databases in the LOCAL mock Docker Compose only.

docker compose exec -T backend python < tests/postgres_smoke.py
Not a pytest unit test: explicitly creates and removes a temporary DB and role.
The production WMS connection is never used.
"""
from __future__ import annotations

from copy import deepcopy
import os
import secrets

import django
import psycopg
from psycopg import sql

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from django.conf import settings
from django.db import DatabaseError, connections
from wms.repository import PostgresRepository


DDL = """
CREATE SCHEMA lk_wms;
CREATE TABLE public.clients_client (id bigint PRIMARY KEY, name text, inn text, is_active bool);
CREATE TABLE public.products_product (id bigint PRIMARY KEY, client_id bigint, sku text, name text, abc_class text, is_active bool);
CREATE TABLE public.stocks_stock (quantity int, reserved_quantity int, product_id bigint, warehouse_id bigint, cell_id bigint, batch_id bigint, box_id bigint, updated_at timestamptz);
CREATE TABLE public.orders_order (id bigint PRIMARY KEY, order_type text, status text, created_at timestamptz, shipment_deadline timestamptz, planned_ship_date date, client_id bigint, marketplace_id bigint, warehouse_id bigint, wave_id bigint);
CREATE TABLE public.receivings_receiving (status text, kind text, received_at timestamptz, created_at timestamptz, confirmed_at timestamptz, client_id bigint, assigned_to_id bigint, return_reason text);
CREATE TABLE public.shipments_shipment (status text, shipped_at timestamptz, created_at timestamptz, order_id bigint, warehouse_id bigint, tracking_number text);
CREATE TABLE public.movements_movement (movement_type text, quantity int, created_at timestamptz, warehouse_id bigint, product_id bigint, created_by_id bigint, order_id bigint, receiving_id bigint, shipment_id bigint, task_id bigint, from_cell_id bigint, to_cell_id bigint, reversal_of_id bigint);
CREATE TABLE public.tasks_task (task_type text, status text, completed_at timestamptz, started_at timestamptz, deadline timestamptz, assigned_to_id bigint, warehouse_id bigint, client_id bigint);
CREATE TABLE public.integrations_integration (is_active bool, last_sync_status text, last_synced_at timestamptz, last_error text, client_id bigint, type_id bigint);
CREATE TABLE lk_wms.orders_receivingrequest (status text, created_at timestamptz, contractor_id bigint, wms_receiving_id bigint);
CREATE TABLE lk_wms.orders_shipmentrequest (status text, created_at timestamptz, contractor_id bigint, wms_order_id bigint);
CREATE TABLE lk_wms.billing_billingcharge (amount numeric, created_at timestamptz, source_type text, contractor_id bigint, service_id bigint, quantity numeric, unit_price numeric, reversal_of_id bigint);
INSERT INTO public.clients_client VALUES (1, 'First client', '123', true), (2, 'Second client', '456', true);
INSERT INTO public.products_product VALUES (10,1,'A','Product A','A',true), (20,2,'B','Product B','B',true);
INSERT INTO public.stocks_stock VALUES (100,25,10,1,1,NULL,NULL,now()), (999,0,20,1,2,NULL,NULL,now());
INSERT INTO public.orders_order VALUES (101,'outbound','confirmed',now(),now()+interval '1 hour',CURRENT_DATE,1,NULL,1,NULL), (201,'outbound','new',now(),NULL,NULL,2,NULL,1,NULL);
INSERT INTO public.receivings_receiving VALUES ('in_receiving','supply',NULL,now(),now(),1,NULL,''), ('draft','supply',NULL,now(),NULL,2,NULL,'');
INSERT INTO public.shipments_shipment VALUES ('shipped',now(),now(),101,1,'track-1'), ('draft',NULL,now(),201,1,'track-2');
INSERT INTO public.movements_movement (movement_type,quantity,created_at,warehouse_id,product_id,reversal_of_id)
VALUES ('receiving',7,now()-interval '1 hour',1,10,NULL),('shipment',3,now()-interval '2 hours',1,10,NULL),('receiving',7,now(),1,10,99),('receiving',900,now(),1,20,NULL);
INSERT INTO public.tasks_task (task_type,status,deadline,client_id) VALUES ('picking','in_progress',now()-interval '2 hours',1), ('picking','done',now()-interval '1 hour',1);
INSERT INTO public.integrations_integration VALUES (true,'error',now()-interval '2 hours','example',1,1);
INSERT INTO lk_wms.orders_receivingrequest VALUES ('submitted',now(),1,NULL), ('accepted',now(),1,1);
INSERT INTO lk_wms.orders_shipmentrequest VALUES ('submitted',now(),1,NULL);
INSERT INTO lk_wms.billing_billingcharge (amount,created_at,source_type,contractor_id,quantity,unit_price,reversal_of_id)
VALUES (100,now(),'storage',1,1,100,NULL),(-20,now(),'storage',1,1,-20,1),(900,now(),'storage',2,1,900,NULL);
"""


def main() -> None:
    assert settings.WMS_MODE == "mock", "Only local DEMO is allowed"
    assert os.environ.get("APP_DB_HOST") == "db", "Use the local Compose backend"
    assert os.environ.get("APP_ENV", "development") == "development"
    own = settings.DATABASES["default"]
    conninfo = dict(host=own["HOST"], port=own["PORT"], user=own["USER"], password=own["PASSWORD"])
    suffix = secrets.token_hex(6)
    database = "pulsar_test_" + suffix
    role = "pulsar_read_" + suffix
    password = secrets.token_urlsafe(24)
    with psycopg.connect(**conninfo, dbname=own["NAME"], autocommit=True) as admin:
        role_created = database_created = False
        try:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
            database_created = True
            admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(role), sql.Literal(password)))
            role_created = True
            with psycopg.connect(**conninfo, dbname=database, autocommit=True) as fixture:
                fixture.execute(DDL)
                fixture.execute(sql.SQL("GRANT USAGE ON SCHEMA public, lk_wms TO {}").format(sql.Identifier(role)))
                fixture.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public, lk_wms TO {}").format(sql.Identifier(role)))
            config = deepcopy(own)
            config.update(NAME=database, USER=role, PASSWORD=password, CONN_MAX_AGE=0)
            config["OPTIONS"] = {"options": "-c default_transaction_read_only=on -c statement_timeout=5000"}
            connections.databases["wms"] = config
            repo = PostgresRepository()
            assert repo.client(1)["name"] == "First client"
            assert repo.client(999) is None
            assert not repo.clients(search="' OR 1=1 --")["results"]
            page1 = repo.clients(page=1, page_size=1)
            page2 = repo.clients(page=2, page_size=1)
            assert page1["has_next"] and len(page1["results"]) == 1
            assert page1["results"] != page2["results"]
            summary = repo.summary(1)
            assert summary["stock"] == {"total": 100, "reserved": 25, "available": 75}
            assert summary["active_orders"] == 1
            assert summary["active_receivings"] == 1
            assert summary["received_units"] == 7
            assert summary["shipped_units"] == 3
            assert float(summary["billing_total"]) == 80
            assert summary["attention"]
            for resource in ("stock", "orders", "receivings", "shipments", "movements"):
                detail = repo.detail(1, resource, page_size=1)
                assert len(detail["results"]) == 1, resource
                assert detail["page"] == 1
            try:
                with connections["wms"].cursor() as cursor:
                    cursor.execute("UPDATE public.stocks_stock SET quantity=0")
            except DatabaseError:
                pass
            else:
                raise AssertionError("WMS connection unexpectedly accepted UPDATE")
            print("OK PostgreSQL repository: schema, joins, parameterization, aggregates, paging, read-only")
        finally:
            if "wms" in connections:
                connections["wms"].close()
            if database_created:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
            if role_created:
                admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


if __name__ == "__main__":
    main()
