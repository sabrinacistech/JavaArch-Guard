"""bytecode_scanner.py — produce state/symbol-contracts/<fqcn>.json from .class bytecode.

Uses `javap -p -s` (private + signatures). For each target FQCN under target/classes,
emit a symbol contract with constructors and methods (with `evidence-id`).
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import atomic_write_json, find_tool, load_json, run, validate

DESC_RE = re.compile(r"descriptor:\s*(\S+)")
ACCESS_RE = re.compile(
    r"^\s*(public|protected|private|default)?\s*"
    r"((?:static|final|abstract|synchronized|native|strictfp|transient|volatile)\s*)*"
    r"(?P<rest>[^;{]+);?$"
)


def _eid(prefix: str, key: str) -> str:
    return f"{prefix}:{hashlib.sha256(key.encode()).hexdigest()[:8]}"


def _parse_desc_params(desc: str) -> list[str]:
    """Parse JVM method descriptor parameters to FQCN-like types."""
    # crude FQCN extraction from JVM desc; not 1:1 with generics but sufficient
    params_section = desc.split(")")[0][1:]
    out: list[str] = []
    i = 0
    while i < len(params_section):
        c = params_section[i]
        arr = ""
        while c == "[":
            arr += "[]"
            i += 1
            c = params_section[i]
        if c == "L":
            end = params_section.index(";", i)
            fq = params_section[i + 1 : end].replace("/", ".")
            out.append(fq + arr)
            i = end + 1
        else:
            primitives = {
                "B": "byte", "C": "char", "D": "double", "F": "float",
                "I": "int", "J": "long", "S": "short", "Z": "boolean", "V": "void",
            }
            out.append(primitives[c] + arr)
            i += 1
    return out


def _parse_desc_return(desc: str) -> str:
    ret = desc.split(")")[1]
    return _parse_desc_params("(" + ret + ")V")[0]  # reuse with a dummy method


def scan_class(class_file: Path, javap: str) -> dict | None:
    r = run([javap, "-p", "-s", str(class_file)])
    if r.returncode != 0:
        return None
    lines = r.stdout.splitlines()
    # First non-empty header line: "public class com.foo.Bar { ..."
    header = next((l for l in lines if l.strip()), "")
    kind = "class"
    if "interface " in header:
        kind = "interface"
    elif "abstract class " in header:
        kind = "abstract"
    elif "enum " in header:
        kind = "enum"
    # Extract FQCN
    m = re.search(r"(class|interface|enum)\s+([\w\.]+)", header)
    if not m:
        return None
    fqcn = m.group(2)

    constructors: list[dict] = []
    methods: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        # Member line + descriptor line
        desc_match = DESC_RE.match(nxt)
        if desc_match:
            desc = desc_match.group(1)
            decl = line.rstrip(";")
            # Constructor: "<FQCN>(...)"
            is_ctor = decl.endswith(")") and (
                decl.startswith("public " + fqcn) or
                decl.startswith("private " + fqcn) or
                decl.startswith("protected " + fqcn) or
                decl.startswith(fqcn)
            )
            visibility = "public"
            for v in ("public", "protected", "private"):
                if decl.startswith(v + " "):
                    visibility = v
                    break
            # parse generic params (raw types) from descriptor
            params = [{"type": t} for t in _parse_desc_params(desc)] if "(" in desc else []
            if is_ctor:
                key = f"{fqcn}({','.join(t['type'] for t in params)})"
                constructors.append(
                    {
                        "evidenceId": _eid(f"ctor:{fqcn}", key),
                        "visibility": visibility,
                        "params": params,
                        "throws": [],
                        "source": f"bytecode:{class_file}",
                    }
                )
            else:
                # method name: token immediately before '('
                name_m = re.search(r"(\w+)\s*\(", decl)
                if not name_m:
                    i += 2
                    continue
                name = name_m.group(1)
                ret = _parse_desc_return(desc)
                modifiers = [
                    m for m in ("public", "protected", "private", "static", "final", "abstract", "synchronized", "native")
                    if (" " + m + " ") in (" " + decl + " ")
                ]
                key = f"{fqcn}#{name}({','.join(t['type'] for t in params)})"
                methods.append(
                    {
                        "evidenceId": _eid(f"sym:{fqcn}#{name}", key),
                        "name": name,
                        "modifiers": modifiers,
                        "returnType": ret,
                        "params": params,
                        "throws": [],
                        "generics": {"typeParams": [], "signature": None},
                        "usable": "synthetic" not in modifiers and name != "<clinit>",
                        "source": "bytecode",
                    }
                )
            i += 2
        else:
            i += 1

    instantiation_allowed = kind == "class" and any(
        c["visibility"] == "public" for c in constructors
    )
    out = {
        "schemaVersion": 1,
        "fqcn": fqcn,
        "kind": kind,
        "modifiers": [],
        "annotations": [],
        "instantiation": {
            "allowed": instantiation_allowed,
            "strategy": "constructor" if instantiation_allowed else "mock",
            "preferred": (constructors[0]["evidenceId"] if instantiation_allowed and constructors else None),
            "fallbacks": [],
        },
        "constructors": constructors,
        "methods": methods,
        "builders": [],
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--module", required=True, help="module dir name")
    ap.add_argument(
        "--include",
        default=".*",
        help="Regex to filter FQCNs (e.g. '^com\\.acme\\.')",
    )
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    state_dir = Path(args.out).resolve()
    mod = repo / args.module
    classes_dir = mod / "target" / "classes"
    if not classes_dir.exists():
        print(f"[FAIL] target/classes missing for {args.module}. Run mvn -DskipTests package first.", file=sys.stderr)
        return 2

    javap = find_tool("javap")
    include = re.compile(args.include)
    out_dir = state_dir / "symbol-contracts"
    out_dir.mkdir(parents=True, exist_ok=True)

    n = 0
    written: list[dict] = []
    for cf in classes_dir.rglob("*.class"):
        # Skip nested/synthetic
        if "$" in cf.name:
            continue
        contract = scan_class(cf, javap)
        if not contract:
            continue
        if not include.search(contract["fqcn"]):
            continue
        try:
            validate("symbol-contract", contract)
        except Exception as e:
            print(f"[WARN] schema failed for {contract['fqcn']}: {e}", file=sys.stderr)
        atomic_write_json(out_dir / f"{contract['fqcn']}.json", contract)
        written.append({
            "fqcn": contract["fqcn"],
            "kind": contract.get("kind", "class"),
            "file": f"{contract['fqcn']}.json",
            "instantiation": contract.get("instantiation", {}).get("strategy", "unknown"),
        })
        n += 1

    # Write/update the manifest (state/symbol-contracts.json) so it reflects
    # the per-FQCN files just written. Agents load individual files by FQCN;
    # the manifest is an index for quick lookup and freshness checks.
    manifest_path = state_dir / "symbol-contracts.json"
    # Merge with any existing entries from other modules
    existing_manifest: list[dict] = []
    if manifest_path.exists():
        try:
            existing_manifest = load_json(manifest_path).get("contracts", [])
            # Remove entries for FQCNs we just re-scanned (they'll be re-added)
            scanned_fqcns = {e["fqcn"] for e in written}
            existing_manifest = [e for e in existing_manifest if e["fqcn"] not in scanned_fqcns]
        except Exception:
            existing_manifest = []
    all_entries = existing_manifest + written
    atomic_write_json(manifest_path, {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "note": "Manifest index of per-FQCN contracts in symbol-contracts/. "
                "Agents load individual files by FQCN, not this manifest.",
        "count": len(all_entries),
        "contracts": sorted(all_entries, key=lambda e: e["fqcn"]),
    })
    print(f"[OK] {n} contracts -> {out_dir}")
    print(f"[OK] manifest -> {manifest_path} ({len(all_entries)} total entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
