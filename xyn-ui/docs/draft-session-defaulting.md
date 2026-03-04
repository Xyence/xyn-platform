# Blueprint Draft Session Defaulting

Default context pack selection is server-side via `GET /xyn/api/context-pack-defaults`.

Rules implemented:
- For `draft_kind=blueprint`: include `xyn-platform-canon` and `xyn-planner-canon`.
- Include `xyence-engineering-conventions` only when `namespace` is present and matches.
- Include `ems-platform-blueprint` only when `project_key == core.ems.platform`.
- Do not include `xyn-coder-canon` for blueprint drafts.
- Include `xyn-coder-canon` when `draft_kind=solution` or `generate_code=true`.

The UI calls the defaults endpoint on draft-create form load and when `kind`, `namespace`, `project_key`, or `generate_code` changes.
If the user has not manually changed context packs, the selection auto-resets to recommended values.
If they already changed it, the UI asks whether to reset.

To add new default packs, update `_recommended_context_pack_ids` in
`xyn-api/backend/xyn_orchestrator/blueprints.py`.
