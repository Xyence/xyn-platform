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
from psycopg2 import sql

from entity_ops import EntityOperationError, GenericEntityOperationsService, PostgresEntityStorageAdapter, RecordContext, load_entity_contracts


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://xyn:xyn_dev_password@localhost:5432/net_inventory")
PORT = int(os.getenv("PORT", "8080"))
SERVICE_NAME = str(os.getenv("SERVICE_NAME", "generated-app-api") or "generated-app-api").strip() or "generated-app-api"
APP_TITLE = str(os.getenv("APP_TITLE", "Generated Application API") or "Generated Application API").strip() or "Generated Application API"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def _postgres_type(field_type: str) -> str:
    normalized = str(field_type or "string").strip().lower()
    if "uuid" in normalized:
        return "UUID"
    if normalized.startswith("datetime"):
        return "TIMESTAMPTZ"
    if normalized.startswith("json"):
        return "JSONB"
    if normalized.startswith("bool"):
        return "BOOLEAN"
    return "TEXT"


def _ensure_contract_schema(cur, contract: dict[str, Any]) -> None:
    table_name = str(contract.get("key") or "").strip()
    if not table_name:
        return
    table = sql.Identifier(table_name)
    cur.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {table} (id UUID PRIMARY KEY)").format(table=table))
    fields = contract.get("fields") if isinstance(contract.get("fields"), list) else []
    seen: set[str] = set()
    for field in fields:
        if not isinstance(field, dict):
            continue
        field_name = str(field.get("name") or "").strip()
        if not field_name or field_name == "id" or field_name in seen:
            continue
        seen.add(field_name)
        default_clause = sql.SQL(" DEFAULT NOW()") if field_name in {"created_at", "updated_at"} and _postgres_type(str(field.get("type") or "")) == "TIMESTAMPTZ" else sql.SQL("")
        cur.execute(
            sql.SQL("ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {column_type}{default_clause}").format(
                table=table,
                column=sql.Identifier(field_name),
                column_type=sql.SQL(_postgres_type(str(field.get("type") or ""))),
                default_clause=default_clause,
            )
        )
    index_workspace = sql.Identifier(f"ix_{table_name}_workspace_id")
    cur.execute(
        sql.SQL("CREATE INDEX IF NOT EXISTS {index_name} ON {table} (workspace_id)").format(
            index_name=index_workspace,
            table=table,
        )
    )
    field_names = {str(field.get("name") or "").strip() for field in fields if isinstance(field, dict)}
    if "status" in field_names:
        index_status = sql.Identifier(f"ix_{table_name}_workspace_status")
        cur.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS {index_name} ON {table} (workspace_id, status)").format(
                index_name=index_status,
                table=table,
            )
        )


def init_schema_with_retry(*, entity_contracts: list[dict[str, Any]]) -> None:
    last_error: Optional[Exception] = None
    for _ in range(30):
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    for contract in entity_contracts:
                        if isinstance(contract, dict):
                            _ensure_contract_schema(cur, contract)
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
    app = FastAPI(title=SERVICE_NAME, version="0.2.0")
    service = entity_service or _build_entity_service()

    if initialize_schema:
        @app.on_event("startup")
        def on_startup() -> None:
            init_schema_with_retry(entity_contracts=list(service.contracts.values()))

    @app.get("/health")
    def health():
        return {"status": "ok", "service": SERVICE_NAME, "time": utc_now()}

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
                <h1>__APP_TITLE__</h1>
                <p>This deployment is running and ready to serve workspace-scoped generated application data through contract-driven CRUD endpoints.</p>
                <ul>
                  <li><a href="/health">/health</a> for service health</li>
                  <li>Entity collection routes are derived from the generated application contract.</li>
                  <li><a href="/docs">/docs</a> for interactive API docs</li>
                </ul>
              </section>
            </main>
          </body>
        </html>
        """.replace("__APP_TITLE__", APP_TITLE)

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
