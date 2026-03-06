# net-inventory-api

Minimal FastAPI service used by Xyn Phase 2 app-builder flow.

## Endpoints

- `GET /health`
- `GET /devices?workspace_id=<uuid>`
- `POST /devices`
- `GET /devices/{id}`
- `GET /reports/devices-by-status?workspace_id=<uuid>`

## Local run

```bash
docker build -f services/net-inventory-api/Dockerfile -t net-inventory-api:local services/net-inventory-api
docker run --rm -p 18080:8080 \
  -e DATABASE_URL=postgresql://xyn:xyn_dev_password@host.docker.internal:5432/net_inventory \
  net-inventory-api:local
```
