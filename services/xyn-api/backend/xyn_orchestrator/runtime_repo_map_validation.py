from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List


DEFAULT_RUNTIME_REPO_MAP = {
    "xyn": ["/workspace/xyn"],
    "xyn-platform": ["/workspace/xyn-platform"],
}


def runtime_repo_map() -> Dict[str, List[Path]]:
    raw = str(os.getenv("XYN_RUNTIME_REPO_MAP", "") or "").strip()
    if raw:
        payload = json.loads(raw)
    else:
        payload = DEFAULT_RUNTIME_REPO_MAP
    if not isinstance(payload, dict):
        raise ValueError("XYN_RUNTIME_REPO_MAP must decode to an object.")
    result: Dict[str, List[Path]] = {}
    for repo_key, value in payload.items():
        if isinstance(value, str):
            entries = [value]
        elif isinstance(value, list):
            entries = [str(item) for item in value if str(item).strip()]
        else:
            raise ValueError(f"Repo mapping for '{repo_key}' must be a string or list.")
        result[str(repo_key)] = [Path(item).expanduser().resolve() for item in entries]
    return result


def validate_runtime_repo_map_targets() -> List[str]:
    warnings: List[str] = []
    repo_map = runtime_repo_map()
    for repo_key, candidates in repo_map.items():
        valid = False
        invalid_reasons: List[str] = []
        for candidate in candidates:
            if not candidate.exists():
                invalid_reasons.append(f"{candidate} (missing)")
                continue
            if not candidate.is_dir():
                invalid_reasons.append(f"{candidate} (not_a_directory)")
                continue
            if not (candidate / ".git").exists():
                invalid_reasons.append(f"{candidate} (not_a_git_repo)")
                continue
            if not os.access(candidate, os.R_OK | os.X_OK):
                invalid_reasons.append(f"{candidate} (not_readable)")
                continue
            valid = True
            break
        if not valid:
            candidate_text = ", ".join(str(path) for path in candidates) or "(none)"
            reason_text = ", ".join(invalid_reasons) if invalid_reasons else "no candidates configured"
            warnings.append(
                f"Runtime repo map target missing for repo '{repo_key}'. candidates=[{candidate_text}] details=[{reason_text}]"
            )
    return warnings
