import subprocess
from pathlib import Path
from typing import Callable, List, Tuple


def git_repo_command(
    *,
    repo_root: Path,
    args: List[str],
    timeout_seconds: int = 20,
) -> Tuple[int, str, str]:
    safe_directory = str(repo_root).strip()
    cmd = ["git", "-c", f"safe.directory={safe_directory}", "-C", str(repo_root), *args]
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = str(exc.stdout or "").strip()
        stderr = str(exc.stderr or "").strip()
        return 124, stdout, stderr or f"command timed out after {timeout_seconds}s"
    except Exception as exc:  # pragma: no cover - defensive
        return 1, "", str(exc)
    return int(proc.returncode or 0), str(proc.stdout or "").strip(), str(proc.stderr or "").strip()


def git_changed_files_for_paths(
    *,
    repo_root: Path,
    pathspecs: List[str],
    git_repo_command_fn: Callable[..., Tuple[int, str, str]],
) -> List[str]:
    scoped = [str(item).strip() for item in pathspecs if str(item).strip()]
    if not scoped:
        return []
    commands = [
        ["diff", "--name-only", "--", *scoped],
        ["diff", "--cached", "--name-only", "--", *scoped],
        ["ls-files", "--others", "--exclude-standard", "--", *scoped],
    ]
    changed: List[str] = []
    seen_keys: set[str] = set()
    for args in commands:
        code, out, _err = git_repo_command_fn(repo_root=repo_root, args=args)
        if code != 0:
            continue
        for line in (out or "").splitlines():
            token = str(line or "").strip()
            if not token:
                continue
            normalized_display = str(token).replace("\\", "/").strip()
            normalized_key = normalized_display.lower()
            if normalized_display and normalized_key not in seen_keys:
                seen_keys.add(normalized_key)
                changed.append(normalized_display)
    return changed


def git_repo_dirty_files(
    repo_root: Path,
    *,
    git_repo_command_fn: Callable[..., Tuple[int, str, str]],
    normalized_repo_path: Callable[[str], str],
) -> Tuple[List[str], str]:
    code, out, err = git_repo_command_fn(repo_root=repo_root, args=["status", "--porcelain"])
    if code != 0:
        return [], err or "git status failed"
    dirty_files: List[str] = []
    for line in (out or "").splitlines():
        token = str(line or "").strip()
        if not token:
            continue
        path_token = token[3:].strip() if len(token) > 3 else token
        if "->" in path_token:
            path_token = path_token.split("->", 1)[1].strip()
        normalized = normalized_repo_path(path_token)
        if normalized and normalized not in dirty_files:
            dirty_files.append(normalized)
    return dirty_files, ""
