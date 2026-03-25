from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from html import escape
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx
import psycopg2
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
SHELL_BASE_URL = str(os.getenv("XYN_SHELL_BASE_URL", "") or "").strip().rstrip("/")


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


def _workspace_id_hint() -> str:
    raw = str(os.getenv("GENERATED_POLICY_BUNDLE_JSON", "") or "").strip()
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("workspace_id") or "").strip()


def _shell_base_url(request: Request) -> str:
    if SHELL_BASE_URL:
        return SHELL_BASE_URL
    referer = str(request.headers.get("referer") or "").strip()
    if not referer:
        return ""
    parsed = urlsplit(referer)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _shell_workbench_url(request: Request) -> str:
    workspace_id = _workspace_id_hint()
    shell_base = _shell_base_url(request)
    if not workspace_id or not shell_base:
        return ""
    return f"{shell_base}/w/{workspace_id}/workbench"


def _render_kv_table(rows: list[dict[str, Any]], *, columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "<p class='empty'>No records found for the current filter.</p>"
    header_html = "".join(f"<th>{escape(label)}</th>" for _, label in columns)
    body_parts: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        tds = []
        for key, _ in columns:
            value = row.get(key)
            if isinstance(value, dict) and str(value.get("href") or "").strip():
                href = str(value.get("href") or "").strip()
                label = str(value.get("label") or href).strip()
                rendered = f"<a href='{escape(href)}'>{escape(label)}</a>"
            elif isinstance(value, (dict, list)):
                rendered = escape(json.dumps(value, separators=(",", ":"))[:220])
            else:
                rendered = escape(str(value if value is not None else ""))
            tds.append(f"<td>{rendered}</td>")
        body_parts.append(f"<tr>{''.join(tds)}</tr>")
    return (
        "<div style='overflow:auto;'>"
        "<table class='kv-table'>"
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(body_parts)}</tbody>"
        "</table>"
        "</div>"
    )


def _render_stat_cards(items: list[tuple[str, Any, str]]) -> str:
    cards: list[str] = []
    for label, value, tone in items:
        cards.append(
            "<article class='stat-card'>"
            f"<p class='stat-label'>{escape(str(label))}</p>"
            f"<p class='stat-value tone-{escape(str(tone))}'>{escape(str(value))}</p>"
            "</article>"
        )
    return f"<section class='stats-grid'>{''.join(cards)}</section>"


def _surface_link(route: str, label: str) -> dict[str, str]:
    return {"href": route, "label": label}


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
          body {{ margin: 0; font-family: ui-sans-serif, system-ui, sans-serif; background: radial-gradient(1400px circle at top left, #1e2b47 0%, #08111f 55%, #07101b 100%); color: #e7edf7; }}
          main {{ max-width: 1160px; margin: 30px auto; padding: 18px; }}
          .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; }}
          .card {{ background: linear-gradient(180deg, #132744 0%, #0b1628 100%); border: 1px solid rgba(148, 163, 184, 0.24); border-radius: 14px; padding: 16px; box-shadow: 0 10px 30px rgba(3,8,16,0.3); }}
          .card > h2 {{ margin-top: 0; }}
          .toolbar {{ display:flex; gap:8px; flex-wrap:wrap; align-items:end; margin: 10px 0 14px; }}
          .toolbar label {{ display:flex; flex-direction:column; gap:4px; font-size:12px; color:#8fb6d9; }}
          input, select, button {{ border-radius: 8px; border: 1px solid rgba(148,163,184,0.35); background:#0a1423; color:#e7edf7; padding:8px 10px; font-size: 13px; }}
          input::placeholder {{ color:#8ba4c0; }}
          button {{ background: linear-gradient(180deg,#1f5ea8,#15457b); cursor:pointer; border-color: rgba(95,161,232,0.65); }}
          button.secondary {{ background: #0f1c2f; border-color: rgba(148,163,184,0.4); }}
          .section {{ margin-top: 12px; }}
          .subtle {{ color:#9fb4cc; font-size: 13px; }}
          .empty {{ color:#9ab0c6; border:1px dashed rgba(148,163,184,0.35); border-radius:10px; padding: 12px; }}
          .kv-table {{ width:100%; border-collapse: collapse; min-width: 640px; }}
          .kv-table thead th {{ position: sticky; top:0; background: rgba(9, 20, 36, 0.95); color:#9ec7f1; font-size: 12px; text-transform: uppercase; letter-spacing: 0.03em; }}
          .kv-table th, .kv-table td {{ border-bottom: 1px solid rgba(148,163,184,0.22); padding: 8px 9px; text-align: left; vertical-align: top; font-size: 13px; }}
          .kv-table tbody tr:hover {{ background: rgba(125, 211, 252, 0.06); }}
          .stats-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(150px,1fr)); gap:10px; margin: 8px 0 14px; }}
          .stat-card {{ border:1px solid rgba(148,163,184,0.28); border-radius: 10px; padding: 10px 12px; background: rgba(10,19,33,0.75); }}
          .stat-label {{ margin:0; color:#8eb2d4; font-size:11px; text-transform:uppercase; letter-spacing:.04em; }}
          .stat-value {{ margin:6px 0 0; font-size:20px; font-weight:700; color:#e8f1fc; }}
          .tone-good {{ color:#79e0ad; }} .tone-warn {{ color:#ffd166; }} .tone-danger {{ color:#ff8b8b; }} .tone-info {{ color:#7dd3fc; }}
          .jump-links {{ display:flex; flex-wrap:wrap; gap:10px; margin-top: 8px; }}
          .jump-links a {{ display:inline-block; padding:6px 10px; border:1px solid rgba(148,163,184,0.3); border-radius:999px; font-size:12px; color:#a7d9ff; background: rgba(15,25,40,0.7); }}
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
    def index(request: Request, view: Optional[str] = Query(default=None)):
        wants_runtime = str(view or "").strip().lower() == "runtime"
        shell_url = _shell_workbench_url(request)
        if shell_url and not wants_runtime:
            return RedirectResponse(url=shell_url, status_code=307)
        return _runtime_launcher(ui_scaffold)

    @app.get("/runtime", response_class=HTMLResponse)
    def runtime_launcher():
        return _runtime_launcher(ui_scaffold)

    def _runtime_launcher(ui_scaffold: dict[str, Any]) -> str:
        return _render_ui_shell(
            ui=ui_scaffold,
            heading="Generated runtime dev surface (use shell/workbench as the primary user entrypoint).",
            body_html="""
                <h2>Runtime Dev Access</h2>
                <p class="subtle">This page is retained for low-level runtime diagnostics. For normal use, open the app through the Xyn shell/workbench.</p>
                <div class="jump-links">
                  <a href="/app">Open App Home</a>
                  <a href="/app/admin">Admin / Operator</a>
                  <a href="/app/campaigns">Campaigns</a>
                  <a href="/app/signals">Signals</a>
                  <a href="/app/surfaces">Surface Directory</a>
                  <a href="/docs">API Docs</a>
                </div>
            """,
        )

    @app.get("/app", response_class=HTMLResponse)
    def app_home():
        body = [
            "<h2>Workflow Overview</h2>",
            "<p class='subtle'>This generated app is organized around two paths: operator source operations and investor campaign monitoring.</p>",
            "<div class='grid'>",
            "<article class='card'><h2>Operator / Source Operations</h2><p>Inspect source health, view funnel status, and trigger unresolved row re-resolution.</p><div class='jump-links'><a href='/app/admin'>Open Admin</a><a href='/app/sources'>Open Sources</a></div></article>",
            "<article class='card'><h2>Campaign Monitoring</h2><p>Review campaigns and inspect watch matches and linked signals by campaign.</p><div class='jump-links'><a href='/app/campaigns'>Open Campaigns</a></div></article>",
            "<article class='card'><h2>Signal Review</h2><p>Review parcel-linked signals and drill into signal details, severity, and context.</p><div class='jump-links'><a href='/app/signals'>Open Signal Feed</a></div></article>",
            "</div>",
        ]
        return _render_ui_shell(
            ui=ui_scaffold,
            heading="Application navigation and workflow entry point.",
            body_html="".join(body),
        )

    @app.get("/app/surfaces")
    def app_surfaces(request: Request):
        accept = str(request.headers.get("accept") or "").lower()
        wants_html = "text/html" in accept or str(request.query_params.get("view") or "").strip().lower() == "html"
        if not wants_html:
            return ui_scaffold
        rows: list[dict[str, Any]] = []
        for section_key, label in (("campaign_user", "Campaign/User"), ("admin_operator", "Admin/Operator")):
            for item in (ui_scaffold.get("groups", {}).get(section_key) or []):
                if isinstance(item, dict):
                    rows.append(
                        {
                            "area": label,
                            "title": str(item.get("title") or ""),
                            "route": _surface_link(str(item.get("route") or ""), str(item.get("route") or "")),
                        }
                    )
        html = _render_ui_shell(
            ui=ui_scaffold,
            heading="Surface directory and navigation map.",
            body_html=(
                "<h2>Available Surfaces</h2>"
                "<p class='subtle'>Generated routes grouped by workflow area.</p>"
                + _render_kv_table(rows, columns=[("area", "Area"), ("title", "Surface"), ("route", "Route")])
            ),
        )
        return HTMLResponse(content=html)

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
            "<p class='subtle'>Live operational context from canonical source, funnel, watch, and signal endpoints.</p>",
            "<form method='get' action='/app/admin' class='toolbar'>"
            f"<label>workspace_id <input name='workspace_id' value='{escape(workspace_token)}' style='min-width:300px;'/></label>"
            f"<label>source_id <input name='source_id' value='{escape(source_token)}' style='min-width:300px;'/></label>"
            "<button type='submit'>Refresh</button>"
            "</form>",
            "<div class='jump-links'><a href='/app/sources'>Source List</a><a href='/app/signals"
            + (f"?workspace_id={escape(workspace_token)}" if workspace_token else "")
            + "'>Signal Feed</a></div>",
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
            body.append(
                _render_stat_cards(
                    [
                        ("Adapted Rows", funnel_counts.get("adapted_rows", 0), "info"),
                        ("Crosswalk Resolved", funnel_counts.get("crosswalk_resolved", 0), "good"),
                        ("Crosswalk Unresolved", funnel_counts.get("crosswalk_unresolved", 0), "warn"),
                        ("Watch Matches", funnel_counts.get("watch_matches_matched", 0), "info"),
                        ("Signal Rows", funnel_counts.get("signal_projection_rows", 0), "good"),
                    ]
                )
            )
            body.append(_render_kv_table([funnel_counts], columns=[("adapted_rows", "Adapted"), ("geocode_selected", "Geocode Selected"), ("crosswalk_resolved", "Crosswalk Resolved"), ("crosswalk_unresolved", "Crosswalk Unresolved"), ("watch_matches_matched", "Watch Matched"), ("signal_projection_rows", "Signal Rows")]))
        unresolved_rows = [row for row in (unresolved or []) if isinstance(row, dict)]
        if unresolved_rows:
            body.append("<h3>Unresolved Reasons</h3>")
            body.append(_render_kv_table(unresolved_rows, columns=[("reason", "Reason"), ("count", "Count")]))
        body.append(
            "<h3>Re-resolve Unresolved Rows</h3>"
            "<p class='subtle'>Retries unresolved crosswalk rows using canonical resolver/geocode evidence. Use after new mapping/geocoding runs.</p>"
            "<form method='post' action='/app/operator/reresolve-source' class='toolbar'>"
            f"<input type='hidden' name='workspace_id' value='{escape(workspace_token)}' />"
            f"<label>source_id <input name='source_id' value='{escape(source_token)}' style='min-width:280px;'/></label>"
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
            "<p class='subtle'>Canonical re-resolution completed. Review the summary and sample rows below.</p>",
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
                f"<p class='subtle'>Entity API endpoint: <code>/{escape(entity_key)}?workspace_id=&lt;workspace_id&gt;</code></p>",
            ]
            if not workspace_token:
                body_parts.append("<p><em>Provide workspace_id in query params to load canonical data.</em></p>")
            if workspace_token and entity_key == "signals":
                body_parts.append(
                    "<form method='get' action='/app/signals' class='toolbar'>"
                    f"<label>workspace_id <input name='workspace_id' value='{escape(workspace_token)}' style='min-width:280px;'/></label>"
                    f"<label>campaign_id <input name='campaign_id' value='{escape(str(request.query_params.get('campaign_id') or ''))}' /></label>"
                    f"<label>watch_id <input name='watch_id' value='{escape(str(request.query_params.get('watch_id') or ''))}' /></label>"
                    f"<label>handle <input name='handle' value='{escape(str(request.query_params.get('handle') or ''))}' /></label>"
                    f"<label>status <input name='status' value='{escape(str(request.query_params.get('status') or ''))}' /></label>"
                    f"<label>severity <input name='severity' value='{escape(str(request.query_params.get('severity') or ''))}' /></label>"
                    "<button type='submit'>Apply Filters</button>"
                    "<a class='secondary' href='/app/signals?workspace_id="
                    + escape(workspace_token)
                    + "' style='display:inline-block;padding:8px 10px;border-radius:8px;'>Clear</a>"
                    "</form>"
                )
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
                            "detail": _surface_link(f"/app/signals/{row.get('id')}?workspace_id={workspace_token}", "View"),
                        }
                    )
                body_parts.append(_render_kv_table(normalized, columns=[("title", "Title"), ("severity", "Severity"), ("status", "Status"), ("campaign_id", "Campaign"), ("watch_id", "Watch"), ("parcel_handle_normalized", "Handle"), ("id", "Signal ID"), ("detail", "Detail")]))
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
                            "open_admin": _surface_link(f"/app/admin?workspace_id={workspace_token}&source_id={row.get('id')}", "Open"),
                        }
                    )
                body_parts.append(_render_kv_table(normalized, columns=[("name", "Name"), ("source_type", "Type"), ("lifecycle_state", "State"), ("is_active", "Active"), ("health_status", "Health"), ("id", "Source ID"), ("open_admin", "Admin")]))
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
                            "open": _surface_link(f"/app/campaigns/{row.get('id')}?workspace_id={workspace_token}", "Open"),
                        }
                    )
                body_parts.append(_render_kv_table(normalized, columns=[("name", "Name"), ("slug", "Slug"), ("status", "Status"), ("id", "Campaign ID"), ("open", "Detail")]))
            return _render_ui_shell(
                ui=ui_scaffold,
                heading=f"{plural_label} list and navigation.",
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
                f"<p class='subtle'>Entity API endpoint: <code>/{escape(entity_key)}/{escape(record_ref)}?workspace_id=&lt;workspace_id&gt;</code></p>",
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
                                    "occurred_at": row.get("occurred_at"),
                                }
                            )
                    body_parts.append(_render_kv_table(rows, columns=[("watch_id", "Watch"), ("matched", "Matched"), ("score", "Score"), ("event_key", "Event Key"), ("reason", "Reason"), ("occurred_at", "Occurred")]))
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
                                    "open": _surface_link(f"/app/signals/{row.get('id')}?workspace_id={workspace_token}", "View"),
                                }
                            )
                    body_parts.append(_render_kv_table(rows, columns=[("title", "Title"), ("severity", "Severity"), ("status", "Status"), ("watch_id", "Watch"), ("id", "Signal ID"), ("open", "Detail")]))
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
                    body_parts.append(_render_stat_cards([("Severity", row.get("severity") or "n/a", "warn"), ("Status", row.get("status") or "n/a", "info"), ("Signal Type", row.get("signal_type") or "n/a", "info")]))
                    body_parts.append(_render_kv_table([{
                        "title": row.get("title"),
                        "severity": row.get("severity"),
                        "status": row.get("status"),
                        "campaign_id": row.get("campaign_id"),
                        "watch_id": row.get("watch_id"),
                        "parcel_handle_normalized": row.get("parcel_handle_normalized"),
                        "event_key": row.get("event_key"),
                    }], columns=[("title", "Title"), ("severity", "Severity"), ("status", "Status"), ("campaign_id", "Campaign"), ("watch_id", "Watch"), ("parcel_handle_normalized", "Handle"), ("event_key", "Event Key")]))
                    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
                    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
                    body_parts.append("<h3>Signal Metadata</h3>")
                    body_parts.append(_render_kv_table([{"occurred_at": row.get("occurred_at"), "source_key": row.get("source_key"), "reconciled_state_version": row.get("reconciled_state_version"), "signal_set_version": row.get("signal_set_version")}], columns=[("occurred_at", "Occurred At"), ("source_key", "Source"), ("reconciled_state_version", "Reconciled Version"), ("signal_set_version", "Signal Set Version")]))
                    if metadata:
                        body_parts.append("<details><summary>Projection Metadata</summary>")
                        body_parts.append(_render_kv_table([metadata], columns=[(key, key.replace("_", " ").title()) for key in sorted(metadata.keys())[:8]]))
                        body_parts.append("</details>")
                    if payload:
                        body_parts.append("<details><summary>Signal Payload</summary>")
                        body_parts.append(_render_kv_table([payload], columns=[(key, key.replace("_", " ").title()) for key in sorted(payload.keys())[:10]]))
                        body_parts.append("</details>")
                else:
                    body_parts.append(f"<p><strong>Signal detail error:</strong> {escape(str(signal_result.get('error') or 'unknown'))}</p>")
            return _render_ui_shell(
                ui=ui_scaffold,
                heading=f"{singular_label} detail and context.",
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
