# xyn-platform

Single source-of-truth monorepo for publishing Xyn platform artifacts consumed by `xyn-seed`.

## Repository layout

- `apps/xyn-ui/` - UI source and Docker build context
- `services/xyn-api/` - API source and Docker build context (publishes `xyn-api`)
- `services/net-inventory-api/` - Network inventory app API source and Docker build context
- `scripts/` - helper scripts for publishing
- `.github/workflows/` - CI publish workflow
- `releases/` - release bridge manifest (`dev.json`)

## Published images

All images are published to:

- `public.ecr.aws/i0h0h0n4/xyn/artifacts/xyn-ui:<tag>`
- `public.ecr.aws/i0h0h0n4/xyn/artifacts/xyn-api:<tag>`
- `public.ecr.aws/i0h0h0n4/xyn/artifacts/net-inventory-api:<tag>`

Tagging policy:

- On push to `main`: `:dev` and `:sha-<shortsha>`
- On `v*` tags: `:vX.Y.Z` and `:stable`

## Local build

```bash
make build
```

This builds:

- `public.ecr.aws/i0h0h0n4/xyn/artifacts/xyn-ui:sha-<shortsha>`
- `public.ecr.aws/i0h0h0n4/xyn/artifacts/xyn-api:sha-<shortsha>`
- `public.ecr.aws/i0h0h0n4/xyn/artifacts/net-inventory-api:sha-<shortsha>`

## Publish dev artifacts

Ensure Docker is running and AWS credentials are available for ECR Public login.

```bash
./scripts/publish_dev.sh
# or
make publish-dev
```

The publish script builds and pushes:

- `public.ecr.aws/i0h0h0n4/xyn/artifacts/xyn-ui:dev`
- `public.ecr.aws/i0h0h0n4/xyn/artifacts/xyn-ui:sha-<shortsha>`
- `public.ecr.aws/i0h0h0n4/xyn/artifacts/xyn-api:dev`
- `public.ecr.aws/i0h0h0n4/xyn/artifacts/xyn-api:sha-<shortsha>`
- `public.ecr.aws/i0h0h0n4/xyn/artifacts/net-inventory-api:dev`
- `public.ecr.aws/i0h0h0n4/xyn/artifacts/net-inventory-api:sha-<shortsha>`

It also writes `releases/dev.json` for seed bridge consumption.

## Auth Mode Adaptation

`xyn-ui` does not use build-time auth mode flags for login behavior. It reads backend runtime auth mode from:

- `/xyn/api/auth/mode`

Backend modes:

- `dev`: local "Continue as Admin" login flow
- `token`: token paste flow
- `oidc`: OIDC provider login flow

## Pre-push publish hook

This repo includes `.githooks/pre-push`, and local Git is configured with `core.hooksPath=.githooks`.

- Every `git push` runs `make publish-dev` first.
- If publish fails, the push is blocked.
- Emergency bypass: `SKIP_XYN_PUBLISH=1 git push`

## CI publishing

GitHub Actions workflow: `.github/workflows/publish.yml`

Triggers:

- push to `main`
- push tags matching `v*`

Required repository secrets (choose one auth mode):

- OIDC (recommended): `AWS_ROLE_TO_ASSUME`
- Access keys: `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`

## License

This repository follows the same GNU Affero General Public License v3.0 model as the core Xyn project.

In plain language, if you modify Xyn runtime or platform components and let users interact with those modified versions over a network, you must also make the corresponding source code for those modifications available under AGPLv3.

Commercial use, including paid hosting, support, and consulting, is allowed so long as AGPL obligations are honored. Separate commercial licensing may also be available.

See [LICENSE](/home/jrestivo/src/xyn-platform/LICENSE) and [NOTICE](/home/jrestivo/src/xyn-platform/NOTICE).

## Trademark and branding

The software license does not grant rights to use project names, logos, or branding except as required for reasonable nominative use.

Any formal trademark policy will be published separately.
