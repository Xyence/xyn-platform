from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from html import escape
from typing import Any, Optional

import psycopg2
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from psycopg2.extras import RealDictCursor
from psycopg2 import sql

from entity_ops import (
    EntityOperationError,
    GenericEntityOperationsService,
    PostgresEntityStorageAdapter,
    RecordContext,
    load_entity_contracts,
    load_policy_bundle,
)


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
        policy_bundle=load_policy_bundle(),
        storage_adapter=PostgresEntityStorageAdapter(get_conn=get_conn),
    )


def _load_json_env(name: str, default: Any) -> Any:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return default
    return parsed


def _titleize(value: str) -> str:
    return str(value or "").replace("_", " ").strip().title()


def _is_admin_entity(entity_key: str) -> bool:
    lowered = str(entity_key or "").lower()
    return any(token in lowered for token in ("source", "connector", "mapping", "inspection", "dataset", "import"))


def _build_ui_scaffold(service: GenericEntityOperationsService) -> dict[str, Any]:
    entities: list[dict[str, Any]] = []
    manage: list[dict[str, str]] = []
    admin: list[dict[str, str]] = []
    workflow_defs = _load_json_env("GENERATED_WORKFLOW_DEFINITIONS_JSON", [])
    primitive_composition = _load_json_env("GENERATED_PLATFORM_PRIMITIVE_COMPOSITION_JSON", [])
    requires_primitives = _load_json_env("GENERATED_REQUIRES_PRIMITIVES_JSON", [])
    ui_surfaces_text = str(os.getenv("GENERATED_UI_SURFACES_TEXT", "") or "").strip().lower()
    workflow_blob = " ".join(
        str(row.get("description") or "")
        for row in workflow_defs
        if isinstance(row, dict)
    ).lower()
    primitive_blob = " ".join(
        " ".join(
            str(item).lower()
            for item in (
                row.get("workflow_key"),
                row.get("workflow_label"),
                row.get("description"),
                " ".join(str(token) for token in (row.get("requires_primitives") or [])),
            )
        )
        for row in primitive_composition
        if isinstance(row, dict)
    )
    requires_set = {str(token or "").strip().lower() for token in requires_primitives if str(token or "").strip()}
    map_required = any(token in workflow_blob for token in ("map", "rectangle", "box", "bounding")) or any(
        token in ui_surfaces_text for token in ("map", "rectangle", "box")
    ) or "geospatial" in requires_set or "geospatial" in primitive_blob
    admin_required = any(token in workflow_blob for token in ("admin", "operator", "source")) or any(
        token in ui_surfaces_text for token in ("admin", "operator", "source")
    )

    for entity_key, contract in service.contracts.items():
        plural_label = str(contract.get("plural_label") or entity_key).strip() or entity_key
        singular_label = str(contract.get("singular_label") or entity_key.rstrip("s")).strip() or entity_key.rstrip("s")
        row = {
            "entity_key": entity_key,
            "title": _titleize(plural_label),
            "list_route": f"/app/{entity_key}",
            "create_route": f"/app/{entity_key}/new",
            "detail_route_template": f"/app/{entity_key}/{{record_ref}}",
        }
        entities.append(row)
        target_group = admin if _is_admin_entity(entity_key) else manage
        target_group.append({"title": f"{_titleize(plural_label)} List", "route": row["list_route"]})
        target_group.append({"title": f"Create {_titleize(singular_label)}", "route": row["create_route"]})

    if map_required:
        manage.insert(0, {"title": "Map Selection", "route": "/app/map-selection"})
    if admin_required:
        admin.insert(0, {"title": "Admin / Operator", "route": "/app/admin"})
    return {
        "app_title": APP_TITLE,
        "entities": entities,
        "groups": {
            "campaign_user": manage,
            "admin_operator": admin,
        },
        "flags": {
            "map_selection_scaffold": map_required,
            "admin_grouping": admin_required or bool(admin),
        },
    }


def _render_ui_shell(*, ui: dict[str, Any], heading: str, body_html: str) -> str:
    user_links = "".join(
        f'<li><a href="{escape(str(item.get("route") or ""))}">{escape(str(item.get("title") or ""))}</a></li>'
        for item in (ui.get("groups", {}).get("campaign_user") or [])
        if isinstance(item, dict)
    )
    admin_links = "".join(
        f'<li><a href="{escape(str(item.get("route") or ""))}">{escape(str(item.get("title") or ""))}</a></li>'
        for item in (ui.get("groups", {}).get("admin_operator") or [])
        if isinstance(item, dict)
    )
    return f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>{escape(APP_TITLE)}</title>
        <style>
          body {{ margin: 0; font-family: ui-sans-serif, system-ui, sans-serif; background: #08111f; color: #e7edf7; }}
          main {{ max-width: 980px; margin: 32px auto; padding: 20px; }}
          .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; }}
          .card {{ background: linear-gradient(180deg, #10203b 0%, #0b1628 100%); border: 1px solid rgba(148, 163, 184, 0.24); border-radius: 14px; padding: 16px; }}
          h1 {{ margin: 0 0 8px; font-size: 28px; }}
          h2 {{ margin: 0 0 8px; font-size: 18px; }}
          p, li {{ color: #c5d0df; line-height: 1.45; }}
          code {{ background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(148, 163, 184, 0.2); border-radius: 6px; padding: 2px 6px; }}
          a {{ color: #7dd3fc; text-decoration: none; }}
          ul {{ margin: 8px 0 0; padding-left: 18px; }}
        </style>
      </head>
      <body>
        <main>
          <section class="card">
            <h1>{escape(APP_TITLE)}</h1>
            <p>{escape(heading)}</p>
          </section>
          <section class="grid" style="margin-top: 14px;">
            <article class="card">
              <h2>Campaign/User Workflows</h2>
              <ul>{user_links or "<li>No campaign surfaces declared.</li>"}</ul>
            </article>
            <article class="card">
              <h2>Admin/Operator Workflows</h2>
              <ul>{admin_links or "<li>No admin/operator surfaces declared.</li>"}</ul>
            </article>
          </section>
          <section class="card" style="margin-top: 14px;">
            {body_html}
          </section>
        </main>
      </body>
    </html>
    """


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
    ui_scaffold = _build_ui_scaffold(service)

    if initialize_schema:
        @app.on_event("startup")
        def on_startup() -> None:
            init_schema_with_retry(entity_contracts=list(service.contracts.values()))

    @app.get("/health")
    def health():
        return {"status": "ok", "service": SERVICE_NAME, "time": utc_now()}

    @app.get("/", response_class=HTMLResponse)
    def index():
        return _render_ui_shell(
            ui=ui_scaffold,
            heading="Generated workflow scaffold surface. Use this shell to navigate campaign/user and admin/operator routes.",
            body_html="""
                <h2>Runtime Access</h2>
                <ul>
                  <li><a href="/app">/app</a> application scaffold home</li>
                  <li><a href="/health">/health</a> for service health</li>
                  <li><a href="/docs">/docs</a> for interactive API docs</li>
                </ul>
            """,
        )

    @app.get("/app", response_class=HTMLResponse)
    def app_home():
        return _render_ui_shell(
            ui=ui_scaffold,
            heading="Application workflow scaffold generated from entity contracts and workflow hints.",
            body_html="""
                <h2>Scaffold Notes</h2>
                <p>These pages are generic scaffolds generated from workflow/entity metadata. Domain logic remains API-driven.</p>
            """,
        )

    @app.get("/app/surfaces")
    def app_surfaces():
        return ui_scaffold

    @app.get("/app/admin", response_class=HTMLResponse)
    def admin_home():
        return _render_ui_shell(
            ui=ui_scaffold,
            heading="Admin/operator scaffold area.",
            body_html="""
                <h2>Admin/Operator Scope</h2>
                <p>Source and operational surfaces are grouped here to keep them separate from campaign-user flows.</p>
            """,
        )

    @app.get("/app/map-selection", response_class=HTMLResponse)
    def map_selection():
        if not bool((ui_scaffold.get("flags") or {}).get("map_selection_scaffold")):
            raise HTTPException(status_code=404, detail="map scaffold not declared")
        return _render_ui_shell(
            ui=ui_scaffold,
            heading="Map/area selection scaffold.",
            body_html="""
                <h2>Map Selection (Scaffold)</h2>
                <p>Map-driven campaign area selection is declared for this app. This placeholder route is generated to anchor map workflow integration.</p>
                <p>Expected behavior: rectangle/box selection over geospatial data.</p>
            """,
        )

    _register_entity_routes(app, service)

    for entity_key, contract in service.contracts.items():
        plural_label = _titleize(str(contract.get("plural_label") or entity_key))
        singular_label = _titleize(str(contract.get("singular_label") or entity_key.rstrip("s")))

        async def entity_list_surface(entity_key: str = entity_key, plural_label: str = plural_label):
            return _render_ui_shell(
                ui=ui_scaffold,
                heading=f"{plural_label} list scaffold.",
                body_html=(
                    f"<h2>{escape(plural_label)} List</h2>"
                    f"<p>API endpoint: <code>/{escape(entity_key)}?workspace_id=&lt;workspace_id&gt;</code></p>"
                ),
            )

        async def entity_create_surface(entity_key: str = entity_key, singular_label: str = singular_label):
            return _render_ui_shell(
                ui=ui_scaffold,
                heading=f"Create {singular_label} scaffold.",
                body_html=(
                    f"<h2>Create {escape(singular_label)}</h2>"
                    f"<p>API endpoint: <code>POST /{escape(entity_key)}</code></p>"
                ),
            )

        async def entity_detail_surface(record_ref: str, entity_key: str = entity_key, singular_label: str = singular_label):
            return _render_ui_shell(
                ui=ui_scaffold,
                heading=f"{singular_label} detail scaffold.",
                body_html=(
                    f"<h2>{escape(singular_label)} Detail</h2>"
                    f"<p>Record ref: <code>{escape(record_ref)}</code></p>"
                    f"<p>API endpoint: <code>/{escape(entity_key)}/{escape(record_ref)}?workspace_id=&lt;workspace_id&gt;</code></p>"
                ),
            )

        app.add_api_route(f"/app/{entity_key}", entity_list_surface, methods=["GET"], response_class=HTMLResponse, name=f"ui-{entity_key}-list")
        app.add_api_route(f"/app/{entity_key}/new", entity_create_surface, methods=["GET"], response_class=HTMLResponse, name=f"ui-{entity_key}-create")
        app.add_api_route(
            f"/app/{entity_key}/{{record_ref}}",
            entity_detail_surface,
            methods=["GET"],
            response_class=HTMLResponse,
            name=f"ui-{entity_key}-detail",
        )

    if "devices" in service.contracts:
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

    if "interfaces" in service.contracts:
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
