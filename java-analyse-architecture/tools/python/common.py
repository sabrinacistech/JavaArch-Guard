"""Shared helpers for tools/python/*.

Keep this dependency-light. Only stdlib + jsonschema + lxml.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

SCHEMAS_DIR = Path(__file__).resolve().parents[1].parent / "state" / "_schemas"


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)
    os.replace(tmp, path)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate(state_name: str, data: Any) -> None:
    """Validate `data` against state/_schemas/<state_name>.schema.json.
    No-op if jsonschema is not installed.
    """
    try:
        import jsonschema  # type: ignore
    except Exception:
        return
    schema_path = SCHEMAS_DIR / f"{state_name}.schema.json"
    if not schema_path.exists():
        return
    with schema_path.open("r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(data, schema)


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout
    )


def find_tool(name: str) -> str:
    p = shutil.which(name)
    if not p:
        raise FileNotFoundError(f"Tool not on PATH: {name}")
    return p


def cache_get(state_dir: Path, key: str, input_hashes: dict[str, str]) -> Any | None:
    cache_file = state_dir / "_cache" / f"{key}.cache.json"
    if not cache_file.exists():
        return None
    try:
        c = load_json(cache_file)
    except Exception:
        return None
    if c.get("inputs") == input_hashes:
        return c.get("output")
    return None


def cache_put(state_dir: Path, key: str, input_hashes: dict[str, str], output: Any) -> None:
    cache_file = state_dir / "_cache" / f"{key}.cache.json"
    atomic_write_json(cache_file, {"inputs": input_hashes, "output": output})


def fail(msg: str, code: int = 2) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(code)


def find_pom_modules(repo: Path) -> list[Path]:
    """Best-effort list of Maven module directories (root + children with pom.xml)."""
    poms = list(repo.rglob("pom.xml"))
    # Skip generated/build dirs
    poms = [p for p in poms if "target" not in p.parts and "build" not in p.parts]
    return [p.parent for p in poms]
