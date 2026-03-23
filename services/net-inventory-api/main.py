from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from html import escape
from typing import Any, Optional

import httpx
import psycopg2
from fastapi import FastAPI, Form, HTTPException, Query, Request
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
PLATFORM_API_BASE_URL = str(os.getenv("XYN_PLATFORM_API_BASE_URL", "") or "").strip()
PLATFORM_API_TIMEOUT_SECONDS = float(os.getenv("XYN_PLATFORM_API_TIMEOUT_SECONDS", "10.0"))
PLATFORM_INTERNAL_TOKEN = str(os.getenv("XYENCE_INTERNAL_TOKEN", "") or "").strip()
PLATFORM_API_HOST_HEADER = str(os.getenv("XYN_PLATFORM_API_HOST_HEADER", "") or "").strip()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def _resolved_platform_api_base_url() -> str:
    base = str(PLATFORM_API_BASE_URL or "").strip()
    if base:
        return base.rstrip("/")
    return "http://xyn-api-backend-1:8000"


def _platform_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json"}
    cookie = str(request.headers.get("cookie") or "").strip()
    if cookie:
        headers["Cookie"] = cookie
    auth = str(request.headers.get("authorization") or "").strip()
    if auth:
        headers["Authorization"] = auth
    csrf = str(request.headers.get("x-csrftoken") or "").strip()
    if csrf:
        headers["X-CSRFToken"] = csrf
    if PLATFORM_INTERNAL_TOKEN:
        headers["X-Internal-Token"] = PLATFORM_INTERNAL_TOKEN
    if PLATFORM_API_HOST_HEADER:
        headers["Host"] = PLATFORM_API_HOST_HEADER
    return headers


def _platform_call(
    request: Request,
    *,
    method: str,
    path: str,
    params: Optional[dict[str, Any]] = None,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    url = f"{_resolved_platform_api_base_url()}{path}"
    try:
        with httpx.Client(timeout=PLATFORM_API_TIMEOUT_SECONDS) as client:
            response = client.request(
                method=method.upper(),
                url=url,
                params=params or None,
                json=payload or None,
                headers=_platform_headers(request),
            )
        body_text = str(response.text or "")
        data: dict[str, Any] = {}
        if body_text:
            try:
                parsed = response.json()
                data = parsed if isinstance(parsed, dict) else {"items": parsed}
            except json.JSONDecodeError:
                data = {}
        return {
            "ok": 200 <= int(response.status_code) < 300,
            "status": int(response.status_code),
            "data": data,
            "error": str(data.get("error") or "").strip() or (body_text[:280] if body_text else ""),
            "url": url,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": 0,
            "data": {},
            "error": f"{exc}",
            "url": url,
        }


def _render_kv_table(rows: list[dict[str, Any]], *, columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "<p><em>No records found.</em></p>"
    header_html = "".join(f"<th>{escape(label)}</th>" for _, label in columns)
    body_parts: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        tds = []
        for key, _ in columns:
            value = row.get(key)
            if isinstance(value, (dict, list)):
                rendered = escape(json.dumps(value, separators=(",", ":"))[:220])
            else:
                rendered = escape(str(value if value is not None else ""))
            tds.append(f"<td>{rendered}</td>")
        body_parts.append(f"<tr>{''.join(tds)}</tr>")
    return (
        "<div style='overflow:auto;'>"
        "<table style='width:100%;border-collapse:collapse'>"
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(body_parts)}</tbody>"
        "</table>"
        "</div>"
    )


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
    def admin_home(
        request: Request,
        workspace_id: Optional[str] = Query(default=None),
        source_id: Optional[str] = Query(default=None),
    ):
        workspace_token = str(workspace_id or "").strip()
        source_token = str(source_id or "").strip()
        sources_result: dict[str, Any] | None = None
        funnel_result: dict[str, Any] | None = None
        if workspace_token:
            sources_result = _platform_call(
                request,
                method="GET",
                path="/xyn/api/source-connectors",
                params={"workspace_id": workspace_token},
            )
            funnel_params: dict[str, Any] = {"workspace_id": workspace_token}
            if source_token:
                funnel_params["source_id"] = source_token
            funnel_result = _platform_call(
                request,
                method="GET",
                path="/xyn/api/monitoring/funnel-summary",
                params=funnel_params,
            )

        sources = list((sources_result or {}).get("data", {}).get("sources") or [])
        funnel_counts = (funnel_result or {}).get("data", {}).get("counts") if isinstance((funnel_result or {}).get("data"), dict) else {}
        unresolved = (
            (funnel_result or {}).get("data", {}).get("unresolved_reasons")
            if isinstance((funnel_result or {}).get("data"), dict)
            else []
        )
        source_rows = [
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "source_type": str(item.get("source_type") or ""),
                "lifecycle_state": str(item.get("lifecycle_state") or ""),
                "is_active": str(bool(item.get("is_active"))),
                "health_status": str(item.get("health_status") or ""),
            }
            for item in sources
            if isinstance(item, dict)
        ]
        body = [
            "<h2>Admin/Operator Scope</h2>",
            "<p>Live operational context from canonical source, funnel, watch, and signal endpoints.</p>",
            "<form method='get' action='/app/admin' style='display:flex;gap:8px;flex-wrap:wrap;margin:10px 0;'>"
            f"<label>workspace_id <input name='workspace_id' value='{escape(workspace_token)}' style='min-width:320px;'/></label>"
            f"<label>source_id <input name='source_id' value='{escape(source_token)}' style='min-width:320px;'/></label>"
            "<button type='submit'>Refresh</button>"
            "</form>",
        ]
        if not workspace_token:
            body.append("<p><em>Provide workspace_id to load source governance and funnel status.</em></p>")
        if sources_result and not sources_result.get("ok"):
            body.append(f"<p><strong>Source API error:</strong> {escape(str(sources_result.get('error') or 'unknown'))}</p>")
        if funnel_result and not funnel_result.get("ok"):
            body.append(f"<p><strong>Funnel API error:</strong> {escape(str(funnel_result.get('error') or 'unknown'))}</p>")
        if source_rows:
            body.append("<h3>Sources</h3>")
            body.append(_render_kv_table(source_rows, columns=[("name", "Name"), ("source_type", "Type"), ("lifecycle_state", "State"), ("is_active", "Active"), ("health_status", "Health"), ("id", "Source ID")]))
        if isinstance(funnel_counts, dict) and funnel_counts:
            body.append("<h3>Monitoring Funnel</h3>")
            body.append(_render_kv_table([funnel_counts], columns=[("adapted_rows", "Adapted"), ("geocode_selected", "Geocode Selected"), ("crosswalk_resolved", "Crosswalk Resolved"), ("crosswalk_unresolved", "Crosswalk Unresolved"), ("watch_matches_matched", "Watch Matched"), ("signal_projection_rows", "Signal Rows")]))
        unresolved_rows = [row for row in (unresolved or []) if isinstance(row, dict)]
        if unresolved_rows:
            body.append("<h3>Unresolved Reasons</h3>")
            body.append(_render_kv_table(unresolved_rows, columns=[("reason", "Reason"), ("count", "Count")]))
        body.append(
            "<h3>Re-resolve Unresolved Rows</h3>"
            "<form method='post' action='/app/operator/reresolve-source' style='display:flex;gap:8px;flex-wrap:wrap;'>"
            f"<input type='hidden' name='workspace_id' value='{escape(workspace_token)}' />"
            f"<label>source_id <input name='source_id' value='{escape(source_token)}' style='min-width:320px;'/></label>"
            "<label>limit <input type='number' name='limit' min='1' max='5000' value='250' /></label>"
            "<label><input type='checkbox' name='require_selected_geocode' value='1' checked /> require selected geocode</label>"
            "<button type='submit'>Run Re-resolution</button>"
            "</form>"
        )
        return _render_ui_shell(
            ui=ui_scaffold,
            heading="Admin/operator scaffold area.",
            body_html="".join(body),
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

    @app.post("/app/operator/reresolve-source", response_class=HTMLResponse)
    async def operator_reresolve_source(
        request: Request,
        workspace_id: str = Form(default=""),
        source_id: str = Form(default=""),
        limit: int = Form(default=250),
        require_selected_geocode: Optional[str] = Form(default=""),
    ):
        workspace_token = str(workspace_id or "").strip()
        source_token = str(source_id or "").strip()
        payload = {
            "workspace_id": workspace_token,
            "source_id": source_token,
            "limit": int(limit or 250),
            "require_selected_geocode": bool(str(require_selected_geocode or "").strip()),
        }
        result = _platform_call(request, method="POST", path="/xyn/api/parcel-crosswalks/reresolve-source", payload=payload)
        rows = list(result.get("data", {}).get("crosswalks") or []) if isinstance(result.get("data"), dict) else []
        summary_row = {
            "status": result.get("status"),
            "count": (result.get("data") or {}).get("count", 0) if isinstance(result.get("data"), dict) else 0,
            "before_unresolved": ((result.get("data") or {}).get("before") or {}).get("unresolved", 0) if isinstance(result.get("data"), dict) else 0,
            "after_unresolved": ((result.get("data") or {}).get("after") or {}).get("unresolved", 0) if isinstance(result.get("data"), dict) else 0,
        }
        body = [
            "<h2>Re-resolution Result</h2>",
            _render_kv_table([summary_row], columns=[("status", "HTTP"), ("count", "Rows Processed"), ("before_unresolved", "Before Unresolved"), ("after_unresolved", "After Unresolved")]),
        ]
        if not result.get("ok"):
            body.append(f"<p><strong>Error:</strong> {escape(str(result.get('error') or 'unknown'))}</p>")
        if rows:
            preview = []
            for row in rows[:20]:
                if isinstance(row, dict):
                    preview.append(
                        {
                            "id": row.get("id"),
                            "status": row.get("status"),
                            "resolution_method": row.get("resolution_method"),
                            "confidence": row.get("confidence"),
                            "reason": row.get("reason"),
                        }
                    )
            body.append("<h3>Crosswalk Preview</h3>")
            body.append(_render_kv_table(preview, columns=[("id", "Crosswalk"), ("status", "Status"), ("resolution_method", "Method"), ("confidence", "Confidence"), ("reason", "Reason")]))
        body.append(f"<p><a href='/app/admin?workspace_id={escape(workspace_token)}&source_id={escape(source_token)}'>Back to Admin</a></p>")
        return _render_ui_shell(ui=ui_scaffold, heading="Canonical parcel crosswalk re-resolution executed.", body_html="".join(body))

    for entity_key, contract in service.contracts.items():
        plural_label = _titleize(str(contract.get("plural_label") or entity_key))
        singular_label = _titleize(str(contract.get("singular_label") or entity_key.rstrip("s")))

        async def entity_list_surface(request: Request, entity_key: str = entity_key, plural_label: str = plural_label):
            workspace_token = _workspace_id_from_request(request)
            body_parts = [
                f"<h2>{escape(plural_label)} List</h2>",
                f"<p>Entity API endpoint: <code>/{escape(entity_key)}?workspace_id=&lt;workspace_id&gt;</code></p>",
            ]
            if not workspace_token:
                body_parts.append("<p><em>Provide workspace_id in query params to load canonical data.</em></p>")
            if workspace_token and entity_key == "signals":
                params: dict[str, Any] = {"workspace_id": workspace_token, "limit": 100}
                for token in ("campaign_id", "watch_id", "handle", "status", "severity", "source_key"):
                    raw = str(request.query_params.get(token) or "").strip()
                    if raw:
                        params[token] = raw
                result = _platform_call(request, method="GET", path="/xyn/api/signals", params=params)
                if not result.get("ok"):
                    body_parts.append(f"<p><strong>Signal feed error:</strong> {escape(str(result.get('error') or 'unknown'))}</p>")
                rows = list((result.get("data") or {}).get("signals") or []) if isinstance(result.get("data"), dict) else []
                normalized = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    normalized.append(
                        {
                            "id": row.get("id"),
                            "title": row.get("title"),
                            "severity": row.get("severity"),
                            "status": row.get("status"),
                            "campaign_id": row.get("campaign_id"),
                            "watch_id": row.get("watch_id"),
                            "parcel_handle_normalized": row.get("parcel_handle_normalized"),
                        }
                    )
                body_parts.append(_render_kv_table(normalized, columns=[("title", "Title"), ("severity", "Severity"), ("status", "Status"), ("campaign_id", "Campaign"), ("watch_id", "Watch"), ("parcel_handle_normalized", "Handle"), ("id", "Signal ID")]))
            if workspace_token and entity_key == "sources":
                result = _platform_call(
                    request,
                    method="GET",
                    path="/xyn/api/source-connectors",
                    params={"workspace_id": workspace_token},
                )
                if not result.get("ok"):
                    body_parts.append(f"<p><strong>Source list error:</strong> {escape(str(result.get('error') or 'unknown'))}</p>")
                rows = list((result.get("data") or {}).get("sources") or []) if isinstance(result.get("data"), dict) else []
                normalized = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    normalized.append(
                        {
                            "name": row.get("name"),
                            "source_type": row.get("source_type"),
                            "lifecycle_state": row.get("lifecycle_state"),
                            "is_active": row.get("is_active"),
                            "health_status": row.get("health_status"),
                            "id": row.get("id"),
                        }
                    )
                body_parts.append(_render_kv_table(normalized, columns=[("name", "Name"), ("source_type", "Type"), ("lifecycle_state", "State"), ("is_active", "Active"), ("health_status", "Health"), ("id", "Source ID")]))
            if workspace_token and entity_key == "campaigns":
                result = _platform_call(
                    request,
                    method="GET",
                    path="/xyn/api/campaigns",
                    params={"workspace_id": workspace_token},
                )
                if not result.get("ok"):
                    body_parts.append(f"<p><strong>Campaign list error:</strong> {escape(str(result.get('error') or 'unknown'))}</p>")
                rows = list((result.get("data") or {}).get("campaigns") or []) if isinstance(result.get("data"), dict) else []
                normalized = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    normalized.append(
                        {
                            "name": row.get("name"),
                            "slug": row.get("slug"),
                            "status": row.get("status"),
                            "id": row.get("id"),
                        }
                    )
                body_parts.append(_render_kv_table(normalized, columns=[("name", "Name"), ("slug", "Slug"), ("status", "Status"), ("id", "Campaign ID")]))
            return _render_ui_shell(
                ui=ui_scaffold,
                heading=f"{plural_label} list scaffold.",
                body_html="".join(body_parts),
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

        async def entity_detail_surface(request: Request, record_ref: str, entity_key: str = entity_key, singular_label: str = singular_label):
            workspace_token = _workspace_id_from_request(request)
            body_parts = [
                f"<h2>{escape(singular_label)} Detail</h2>",
                f"<p>Record ref: <code>{escape(record_ref)}</code></p>",
                f"<p>Entity API endpoint: <code>/{escape(entity_key)}/{escape(record_ref)}?workspace_id=&lt;workspace_id&gt;</code></p>",
            ]
            if workspace_token and entity_key == "campaigns":
                campaign_result = _platform_call(
                    request,
                    method="GET",
                    path=f"/xyn/api/campaigns/{record_ref}",
                    params={"workspace_id": workspace_token},
                )
                if campaign_result.get("ok"):
                    campaign_payload = campaign_result.get("data") if isinstance(campaign_result.get("data"), dict) else {}
                    body_parts.append("<h3>Campaign</h3>")
                    body_parts.append(
                        _render_kv_table(
                            [
                                {
                                    "name": campaign_payload.get("name"),
                                    "slug": campaign_payload.get("slug"),
                                    "status": campaign_payload.get("status"),
                                    "type": campaign_payload.get("campaign_type"),
                                }
                            ],
                            columns=[("name", "Name"), ("slug", "Slug"), ("status", "Status"), ("type", "Type")],
                        )
                    )
                else:
                    body_parts.append(f"<p><strong>Campaign detail error:</strong> {escape(str(campaign_result.get('error') or 'unknown'))}</p>")
                match_result = _platform_call(
                    request,
                    method="GET",
                    path="/xyn/api/watches/matches",
                    params={"workspace_id": workspace_token, "campaign_id": record_ref, "limit": 50},
                )
                signal_result = _platform_call(
                    request,
                    method="GET",
                    path="/xyn/api/signals",
                    params={"workspace_id": workspace_token, "campaign_id": record_ref, "limit": 50},
                )
                if match_result.get("ok"):
                    matches = list((match_result.get("data") or {}).get("matches") or []) if isinstance(match_result.get("data"), dict) else []
                    body_parts.append("<h3>Watch Matches</h3>")
                    rows = []
                    for row in matches:
                        if isinstance(row, dict):
                            rows.append(
                                {
                                    "watch_id": row.get("watch_id"),
                                    "matched": row.get("matched"),
                                    "score": row.get("score"),
                                    "event_key": row.get("event_key"),
                                    "reason": row.get("reason"),
                                }
                            )
                    body_parts.append(_render_kv_table(rows, columns=[("watch_id", "Watch"), ("matched", "Matched"), ("score", "Score"), ("event_key", "Event Key"), ("reason", "Reason")]))
                if signal_result.get("ok"):
                    signals = list((signal_result.get("data") or {}).get("signals") or []) if isinstance(signal_result.get("data"), dict) else []
                    body_parts.append("<h3>Signals</h3>")
                    rows = []
                    for row in signals:
                        if isinstance(row, dict):
                            rows.append(
                                {
                                    "title": row.get("title"),
                                    "severity": row.get("severity"),
                                    "status": row.get("status"),
                                    "watch_id": row.get("watch_id"),
                                    "id": row.get("id"),
                                }
                            )
                    body_parts.append(_render_kv_table(rows, columns=[("title", "Title"), ("severity", "Severity"), ("status", "Status"), ("watch_id", "Watch"), ("id", "Signal ID")]))
            if workspace_token and entity_key == "signals":
                signal_result = _platform_call(
                    request,
                    method="GET",
                    path=f"/xyn/api/signals/{record_ref}",
                    params={"workspace_id": workspace_token},
                )
                if signal_result.get("ok"):
                    row = signal_result.get("data") if isinstance(signal_result.get("data"), dict) else {}
                    body_parts.append("<h3>Signal Detail</h3>")
                    body_parts.append(_render_kv_table([{
                        "title": row.get("title"),
                        "severity": row.get("severity"),
                        "status": row.get("status"),
                        "campaign_id": row.get("campaign_id"),
                        "watch_id": row.get("watch_id"),
                        "parcel_handle_normalized": row.get("parcel_handle_normalized"),
                        "event_key": row.get("event_key"),
                    }], columns=[("title", "Title"), ("severity", "Severity"), ("status", "Status"), ("campaign_id", "Campaign"), ("watch_id", "Watch"), ("parcel_handle_normalized", "Handle"), ("event_key", "Event Key")]))
                else:
                    body_parts.append(f"<p><strong>Signal detail error:</strong> {escape(str(signal_result.get('error') or 'unknown'))}</p>")
            return _render_ui_shell(
                ui=ui_scaffold,
                heading=f"{singular_label} detail scaffold.",
                body_html="".join(body_parts),
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
