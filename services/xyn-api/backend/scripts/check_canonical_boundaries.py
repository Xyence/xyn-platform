#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    backend_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend_root))

    from xyn_orchestrator.guardrails import scan_backend_canonical_drift

    findings = scan_backend_canonical_drift(backend_root)
    if findings:
        print("[boundary-guard] Canonical-boundary drift findings detected:")
        for finding in findings:
            print(f" - {finding}")
        print("[boundary-guard] Fail: resolve findings or update allowlists intentionally.")
        return 1

    print("[boundary-guard] OK: no canonical-boundary drift findings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
