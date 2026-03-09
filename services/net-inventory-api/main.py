from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import psycopg2
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor


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
                          city TEXT NULL,
                          region TEXT NULL,
                          country TEXT NULL,
                          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                    cur.execute("CREATE INDEX IF NOT EXISTS ix_locations_workspace_id ON locations(workspace_id)")
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


app = FastAPI(title="net-inventory-api", version="0.1.0")


class DeviceCreateRequest(BaseModel):
    workspace_id: uuid.UUID
    name: str = Field(min_length=1)
    kind: str = "device"
    status: str = "unknown"
    location_id: Optional[uuid.UUID] = None


class LocationCreateRequest(BaseModel):
    workspace_id: uuid.UUID
    name: str = Field(min_length=1)
    kind: str = "site"
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None


class InterfaceCreateRequest(BaseModel):
    workspace_id: uuid.UUID
    device_id: uuid.UUID
    name: str = Field(min_length=1)
    status: str = "unknown"


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
          body {
            margin: 0;
            font-family: ui-sans-serif, system-ui, sans-serif;
            background: #08111f;
            color: #e7edf7;
          }
          main {
            max-width: 760px;
            margin: 48px auto;
            padding: 24px;
          }
          .card {
            background: linear-gradient(180deg, #10203b 0%, #0b1628 100%);
            border: 1px solid rgba(148, 163, 184, 0.24);
            border-radius: 18px;
            padding: 24px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.28);
          }
          h1 {
            margin: 0 0 12px;
            font-size: 28px;
          }
          p, li {
            color: #c5d0df;
            line-height: 1.5;
          }
          code {
            background: rgba(15, 23, 42, 0.8);
            border: 1px solid rgba(148, 163, 184, 0.2);
            border-radius: 8px;
            padding: 2px 6px;
          }
          a {
            color: #7dd3fc;
          }
        </style>
      </head>
      <body>
        <main>
          <section class="card">
            <h1>Net Inventory API</h1>
            <p>This deployment is running and ready to serve workspace-scoped device inventory data.</p>
            <ul>
              <li><a href="/health">/health</a> for service health</li>
              <li><code>GET /devices?workspace_id=&lt;uuid&gt;</code> to list devices</li>
              <li><code>POST /devices</code> to create a device</li>
              <li><code>GET /locations?workspace_id=&lt;uuid&gt;</code> to list locations</li>
              <li><code>POST /locations</code> to create a location</li>
              <li><code>GET /interfaces?workspace_id=&lt;uuid&gt;</code> to list interfaces</li>
              <li><code>POST /interfaces</code> to create an interface</li>
              <li><code>GET /reports/devices-by-status?workspace_id=&lt;uuid&gt;</code> for the chart dataset</li>
              <li><code>GET /reports/interfaces-by-status?workspace_id=&lt;uuid&gt;</code> for the interface chart dataset</li>
              <li><a href="/docs">/docs</a> for interactive API docs</li>
            </ul>
          </section>
        </main>
      </body>
    </html>
    """


@app.get("/devices")
def list_devices(workspace_id: uuid.UUID = Query(...)):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, workspace_id, name, kind, status, location_id, created_at, updated_at
                FROM devices
                WHERE workspace_id = %s
                ORDER BY created_at DESC
                """,
                (str(workspace_id),),
            )
            rows = cur.fetchall()
    return {"items": rows}


@app.post("/devices", status_code=201)
def create_device(payload: DeviceCreateRequest):
    row_id = uuid.uuid4()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO devices (id, workspace_id, name, kind, status, location_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
                """,
                (
                    str(row_id),
                    str(payload.workspace_id),
                    payload.name.strip(),
                    payload.kind.strip() or "device",
                    payload.status.strip() or "unknown",
                    str(payload.location_id) if payload.location_id else None,
                ),
            )
            cur.execute(
                """
                SELECT id, workspace_id, name, kind, status, location_id, created_at, updated_at
                FROM devices WHERE id = %s
                """,
                (str(row_id),),
            )
            row = cur.fetchone()
        conn.commit()
    return row


@app.get("/locations")
def list_locations(workspace_id: uuid.UUID = Query(...)):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, workspace_id, name, kind, city, region, country, created_at, updated_at
                FROM locations
                WHERE workspace_id = %s
                ORDER BY created_at DESC
                """,
                (str(workspace_id),),
            )
            rows = cur.fetchall()
    return {"items": rows}


@app.post("/locations", status_code=201)
def create_location(payload: LocationCreateRequest):
    row_id = uuid.uuid4()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO locations (id, workspace_id, name, kind, city, region, country, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                """,
                (
                    str(row_id),
                    str(payload.workspace_id),
                    payload.name.strip(),
                    payload.kind.strip() or "site",
                    payload.city.strip() if payload.city else None,
                    payload.region.strip() if payload.region else None,
                    payload.country.strip() if payload.country else None,
                ),
            )
            cur.execute(
                """
                SELECT id, workspace_id, name, kind, city, region, country, created_at, updated_at
                FROM locations WHERE id = %s
                """,
                (str(row_id),),
            )
            row = cur.fetchone()
        conn.commit()
    return row


@app.get("/locations/{location_id}")
def get_location(location_id: uuid.UUID):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, workspace_id, name, kind, city, region, country, created_at, updated_at
                FROM locations WHERE id = %s
                """,
                (str(location_id),),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Location not found")
    return row


@app.get("/devices/{device_id}")
def get_device(device_id: uuid.UUID):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, workspace_id, name, kind, status, location_id, created_at, updated_at
                FROM devices WHERE id = %s
                """,
                (str(device_id),),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Device not found")
    return row


@app.get("/interfaces")
def list_interfaces(workspace_id: uuid.UUID = Query(...)):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, workspace_id, device_id, name, status, created_at, updated_at
                FROM interfaces
                WHERE workspace_id = %s
                ORDER BY created_at DESC
                """,
                (str(workspace_id),),
            )
            rows = cur.fetchall()
    return {"items": rows}


@app.post("/interfaces", status_code=201)
def create_interface(payload: InterfaceCreateRequest):
    row_id = uuid.uuid4()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO interfaces (id, workspace_id, device_id, name, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                """,
                (
                    str(row_id),
                    str(payload.workspace_id),
                    str(payload.device_id),
                    payload.name.strip(),
                    payload.status.strip() or "unknown",
                ),
            )
            cur.execute(
                """
                SELECT id, workspace_id, device_id, name, status, created_at, updated_at
                FROM interfaces WHERE id = %s
                """,
                (str(row_id),),
            )
            row = cur.fetchone()
        conn.commit()
    return row


@app.get("/interfaces/{interface_id}")
def get_interface(interface_id: uuid.UUID):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, workspace_id, device_id, name, status, created_at, updated_at
                FROM interfaces WHERE id = %s
                """,
                (str(interface_id),),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Interface not found")
    return row


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=PORT)
