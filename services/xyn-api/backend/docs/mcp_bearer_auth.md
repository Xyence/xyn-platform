# MCP Bearer Auth Model

## Why this change

`/xyn/api/*` workflow routes (applications, change sessions, runtime runs, decomposition) are protected by `@login_required` and downstream identity checks. MCP server-to-server calls were failing because the backend identity resolver only trusted `request.session["user_identity_id"]`.

That forced browser-cookie workarounds, which are not acceptable for production MCP flows.

## Chosen model

- Browser UI: existing Django session auth remains supported.
- MCP/server-to-server: OAuth/OIDC bearer tokens are accepted and validated in middleware.
- Both resolve to the same internal principal: `UserIdentity`.

This keeps workspace membership and capability checks unchanged.

## Identity propagation path

1. MCP receives a bearer token from the caller.
2. MCP forwards `Authorization: Bearer ...` upstream.
3. `ApiTokenAuthMiddleware` validates bearer token (`_verify_oidc_token`).
4. Middleware upserts/resolves `UserIdentity` from claims (`iss`, `sub`, `email`) and stores request-scoped identity id.
5. `_require_authenticated` resolves identity from:
   - request-scoped bearer identity id
   - session identity id
   - user->identity fallback
6. Existing membership/capability checks execute unchanged.

## Route auth matrix (current)

| Route group | Auth gate | Identity source | Bearer support |
| --- | --- | --- | --- |
| `/xyn/api/artifacts*` | `@login_required` + staff/capability checks | request user + `_require_authenticated` where used | Yes |
| `/xyn/api/applications*` | `@login_required` + `_require_authenticated` + workspace checks | unified resolver | Yes |
| change-session routes | `@login_required` + `_require_authenticated` + workspace/capability checks | unified resolver | Yes |
| runtime-run routes | `@login_required` + `_require_authenticated` + workspace checks | unified resolver | Yes |
| decomposition/goal routes | `@login_required` + `_require_authenticated` + workspace checks | unified resolver | Yes |

## Cookie injection status

Browser cookie forwarding is rejected as a primary auth mechanism for MCP. Cookie handling may exist only as a temporary, deprecated fallback and must not be required for normal operation.
