from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg2
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from psycopg2.extras import RealDictCursor

from entity_ops import EntityOperationError, GenericEntityOperationsService, PostgresEntityStorageAdapter, RecordContext, load_entity_contracts


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://xyn:xyn_dev_password@localhost:5432/net_inventory")
PORT = int(os.getenv("PORT", "8080"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_schema_with_retry() -> None:
    last_error: Optional[Exception] = None
    for _ in range(30):
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS devices (
                          id UUID PRIMARY KEY,
                          workspace_id UUID NOT NULL,
                          name TEXT NOT NULL,
                          kind TEXT NOT NULL DEFAULT 'device',
                          status TEXT NOT NULL DEFAULT 'unknown',
                          location_id UUID NULL,
                          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                    cur.execute("CREATE INDEX IF NOT EXISTS ix_devices_workspace_id ON devices(workspace_id)")
                    cur.execute("CREATE INDEX IF NOT EXISTS ix_devices_workspace_status ON devices(workspace_id, status)")
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS locations (
                          id UUID PRIMARY KEY,
                          workspace_id UUID NOT NULL,
                          name TEXT NOT NULL,
                          kind TEXT NOT NULL DEFAULT 'site',
                          parent_location_id UUID NULL,
                          address_line1 TEXT NULL,
                          address_line2 TEXT NULL,
                          city TEXT NULL,
                          region TEXT NULL,
                          postal_code TEXT NULL,
                          country TEXT NULL,
                          notes TEXT NULL,
                          tags_json JSONB NULL,
                          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                    cur.execute("CREATE INDEX IF NOT EXISTS ix_locations_workspace_id ON locations(workspace_id)")
                    cur.execute("ALTER TABLE locations ADD COLUMN IF NOT EXISTS parent_location_id UUID NULL")
                    cur.execute("ALTER TABLE locations ADD COLUMN IF NOT EXISTS address_line1 TEXT NULL")
                    cur.execute("ALTER TABLE locations ADD COLUMN IF NOT EXISTS address_line2 TEXT NULL")
                    cur.execute("ALTER TABLE locations ADD COLUMN IF NOT EXISTS postal_code TEXT NULL")
                    cur.execute("ALTER TABLE locations ADD COLUMN IF NOT EXISTS notes TEXT NULL")
                    cur.execute("ALTER TABLE locations ADD COLUMN IF NOT EXISTS tags_json JSONB NULL")
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS interfaces (
                          id UUID PRIMARY KEY,
                          workspace_id UUID NOT NULL,
                          device_id UUID NOT NULL,
                          name TEXT NOT NULL,
                          status TEXT NOT NULL DEFAULT 'unknown',
                          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                    cur.execute("CREATE INDEX IF NOT EXISTS ix_interfaces_workspace_id ON interfaces(workspace_id)")
                    cur.execute("CREATE INDEX IF NOT EXISTS ix_interfaces_workspace_status ON interfaces(workspace_id, status)")
                conn.commit()
            return
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"Failed to initialize schema: {last_error}")


def _workspace_id_from_request(request: Request) -> Optional[str]:
    raw = str(request.query_params.get("workspace_id") or "").strip()
    return raw or None


def _http_error(exc: EntityOperationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _build_entity_service() -> GenericEntityOperationsService:
    return GenericEntityOperationsService(
        entity_contracts=load_entity_contracts(),
        storage_adapter=PostgresEntityStorageAdapter(get_conn=get_conn),
    )


def _register_entity_routes(app: FastAPI, service: GenericEntityOperationsService) -> None:
    for entity_key, contract in service.contracts.items():
        collection_path = str(contract.get("collection_path") or f"/{entity_key}")
        item_path = str(contract.get("item_path_template") or f"/{entity_key}" + "/{id}").replace("{id}", "{record_ref}")
        operations = contract.get("operations") if isinstance(contract.get("operations"), dict) else {}

        if bool((operations.get("list") or {}).get("declared")):
            async def list_handler(request: Request, entity_key: str = entity_key):
                try:
                    items = service.list_records(entity_key, context=RecordContext(workspace_id=_workspace_id_from_request(request)))
                except EntityOperationError as exc:
                    raise _http_error(exc) from exc
                return {"items": items}

            app.add_api_route(collection_path, list_handler, methods=["GET"], name=f"{entity_key}-list")

        if bool((operations.get("create") or {}).get("declared")):
            async def create_handler(request: Request, entity_key: str = entity_key):
                payload = await request.json()
                try:
                    return service.create_record(entity_key, payload, context=RecordContext(workspace_id=_workspace_id_from_request(request)))
                except EntityOperationError as exc:
                    raise _http_error(exc) from exc

            app.add_api_route(collection_path, create_handler, methods=["POST"], status_code=201, name=f"{entity_key}-create")

        if bool((operations.get("get") or {}).get("declared")):
            async def get_handler(record_ref: str, request: Request, entity_key: str = entity_key):
                try:
                    return service.get_record(entity_key, record_ref, context=RecordContext(workspace_id=_workspace_id_from_request(request)))
                except EntityOperationError as exc:
                    raise _http_error(exc) from exc

            app.add_api_route(item_path, get_handler, methods=["GET"], name=f"{entity_key}-get")

        if bool((operations.get("update") or {}).get("declared")):
            async def update_handler(record_ref: str, request: Request, entity_key: str = entity_key):
                payload = await request.json()
                try:
                    return service.update_record(entity_key, record_ref, payload, context=RecordContext(workspace_id=_workspace_id_from_request(request)))
                except EntityOperationError as exc:
                    raise _http_error(exc) from exc

            app.add_api_route(item_path, update_handler, methods=["PATCH"], name=f"{entity_key}-update")

        if bool((operations.get("delete") or {}).get("declared")):
            async def delete_handler(record_ref: str, request: Request, entity_key: str = entity_key):
                try:
                    deleted = service.delete_record(entity_key, record_ref, context=RecordContext(workspace_id=_workspace_id_from_request(request)))
                except EntityOperationError as exc:
                    raise _http_error(exc) from exc
                return {"deleted": True, "item": deleted}

            app.add_api_route(item_path, delete_handler, methods=["DELETE"], name=f"{entity_key}-delete")


def create_app(*, entity_service: Optional[GenericEntityOperationsService] = None, initialize_schema: bool = True) -> FastAPI:
    app = FastAPI(title="net-inventory-api", version="0.2.0")
    service = entity_service or _build_entity_service()

    if initialize_schema:
        @app.on_event("startup")
        def on_startup() -> None:
            init_schema_with_retry()

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "net-inventory-api", "time": utc_now()}

    @app.get("/", response_class=HTMLResponse)
    def index():
        return """
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1" />
            <title>Net Inventory API</title>
            <style>
              body { margin: 0; font-family: ui-sans-serif, system-ui, sans-serif; background: #08111f; color: #e7edf7; }
              main { max-width: 760px; margin: 48px auto; padding: 24px; }
              .card { background: linear-gradient(180deg, #10203b 0%, #0b1628 100%); border: 1px solid rgba(148, 163, 184, 0.24); border-radius: 18px; padding: 24px; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.28); }
              h1 { margin: 0 0 12px; font-size: 28px; }
              p, li { color: #c5d0df; line-height: 1.5; }
              code { background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(148, 163, 184, 0.2); border-radius: 8px; padding: 2px 6px; }
              a { color: #7dd3fc; }
            </style>
          </head>
          <body>
            <main>
              <section class="card">
                <h1>Net Inventory API</h1>
                <p>This deployment is running and ready to serve workspace-scoped inventory data through generic entity CRUD endpoints.</p>
                <ul>
                  <li><a href="/health">/health</a> for service health</li>
                  <li><code>GET /devices?workspace_id=&lt;uuid&gt;</code> to list devices</li>
                  <li><code>POST /devices</code> to create a device</li>
                  <li><code>PATCH /devices/{id}</code> to update a device</li>
                  <li><code>DELETE /devices/{id}</code> to delete a device</li>
                  <li><code>GET /locations?workspace_id=&lt;uuid&gt;</code> to list locations</li>
                  <li><code>POST /locations</code> to create a location</li>
                  <li><code>GET /reports/devices-by-status?workspace_id=&lt;uuid&gt;</code> for the chart dataset</li>
                  <li><code>GET /reports/interfaces-by-status?workspace_id=&lt;uuid&gt;</code> for the interface chart dataset</li>
                  <li><a href="/docs">/docs</a> for interactive API docs</li>
                </ul>
              </section>
            </main>
          </body>
        </html>
        """

    _register_entity_routes(app, service)

    @app.get("/reports/devices-by-status")
    def report_devices_by_status(workspace_id: uuid.UUID = Query(...)):
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status, COUNT(*)::int AS total
                    FROM devices
                    WHERE workspace_id = %s
                    GROUP BY status
                    ORDER BY status ASC
                    """,
                    (str(workspace_id),),
                )
                rows = cur.fetchall()
        labels = [str(row.get("status") or "unknown") for row in rows]
        values = [int(row.get("total") or 0) for row in rows]
        return {"labels": labels, "values": values}

    @app.get("/reports/interfaces-by-status")
    def report_interfaces_by_status(workspace_id: uuid.UUID = Query(...)):
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status, COUNT(*)::int AS total
                    FROM interfaces
                    WHERE workspace_id = %s
                    GROUP BY status
                    ORDER BY status ASC
                    """,
                    (str(workspace_id),),
                )
                rows = cur.fetchall()
        labels = [str(row.get("status") or "unknown") for row in rows]
        values = [int(row.get("total") or 0) for row in rows]
        return {"labels": labels, "values": values}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=PORT)
