from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import psycopg2
from fastapi import FastAPI, HTTPException, Query
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


@app.on_event("startup")
def on_startup() -> None:
    init_schema_with_retry()


@app.get("/health")
def health():
    return {"status": "ok", "service": "net-inventory-api", "time": utc_now()}


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=PORT)
