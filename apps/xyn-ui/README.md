# xyn-ui

Mobile-first provisioning UI for Xyn Seed.

## Requirements
- Node.js 18+
- npm / pnpm / yarn

## Setup
```bash
cp .env.example .env
npm install
npm run dev
```

## Environment
- `VITE_API_BASE_URL` (default: current origin)
- `VITE_AUTH_MODE` (dev|oidc) default dev
- `VITE_XYN_UI_ENABLE_LEGACY_CONTROL_PLANE` default `false`
- `VITE_XYN_UI_ENABLE_LEGACY_GUIDES` default `false`
- `VITE_XYN_UI_ENABLE_LEGACY_DEV_TASKS_PAGE` default `false`
- `VITE_XYN_UI_ENABLE_LEGACY_BLUEPRINTS` default `false`

## Notes
This UI relies on existing xyn-api staff session cookies in dev mode.

## Shared Login
- Apps should redirect users to the platform login route:
  - `/auth/login?appId=<appId>&returnTo=<url>`
- Do not implement app-specific provider pickers in individual apps.

## Bug / Feature Report Overlay
- Open with `Ctrl+Shift+B` (or `Cmd+Shift+B` on macOS).
- Supports:
  - report type, title, description, priority, tags
  - drag/drop or paste image attachments
  - context capture preview
  - `Copy debug bundle` (copies captured context JSON to clipboard)

## Platform Settings
- Admin screen at `Platform -> Platform Settings` manages:
  - attachment storage provider config (`local` / `s3`)
  - report notifications config (Discord + SNS)

## UI Kit + Dynamic Theme
- `src/ui-kit` provides a lightweight shared shell/components using plain CSS variables:
  - `AppShell`, `Header`, `Footer`, `Page`, `Card`, `Button`, `Input`, `TableWrap`
- `ensureXynThemeCss(appKey, endpointBase)` injects:
  - `/xyn/api/branding/theme.css?app=<appKey>`
- Avatar/login/branding flows can continue using existing APIs; generated apps now have a minimum visual baseline out of the box.

## SPA routing fallback
When deploying behind a reverse proxy, ensure all public routes (e.g. `/about`, `/articles`, `/articles/:slug`) resolve to `index.html`. The provided `nginx.conf` already includes:

```
location / {
  try_files $uri /index.html;
}
```

If using a different proxy, replicate that behavior.
