from __future__ import annotations

from pathlib import Path


class PolicyError(RuntimeError):
    """Raised when a requested operation violates a runtime policy."""


def resolve_under(root: str | Path, candidate: str | Path) -> Path:
    safe_root = Path(root).expanduser().resolve(strict=True)
    raw = Path(candidate).expanduser()
    resolved = (safe_root / raw).resolve(strict=False) if not raw.is_absolute() else raw.resolve(strict=False)
    try:
        resolved.relative_to(safe_root)
    except ValueError as exc:
        raise PolicyError(f"Path is outside workspace root: {resolved}") from exc
    return resolved


def reject_git_metadata(path: Path, repo: Path) -> None:
    relative = path.relative_to(repo)
    if relative.parts and relative.parts[0].lower() == ".git":
        raise PolicyError("Direct access to .git metadata is forbidden")

