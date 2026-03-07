## Context-Pack Runtime Bridge

`xyn-platform` owns context-pack identity and governance.

Current bridge
- Authoritative seed/model logic lives in Django:
  - `xyn_orchestrator/models.py`
  - `xyn_orchestrator/artifact_links.py`
  - `seeds/xyn-core-context-packs.v1.2.0.json`
- Runtime export script:
  - `scripts/export_core_context_packs.py`
- `xynctl` in the sibling `xyn` repo runs that script and writes:
  - `.xyn/sync/context-packs.manifest.json`

This keeps `xyn-core` runtime inventory and bindings aligned to `xyn-platform` slugs such as:
- `xyn-console-default`
- `xyn-planner-canon`

Transitional note
- This is a synchronization bridge, not the final publish/import/install path.
- The next architectural step is to promote context packs as published/synced artifacts that `xyn-core` imports instead of consuming a local runtime manifest.
