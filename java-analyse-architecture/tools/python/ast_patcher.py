"""ast_patcher.py — conservative text patcher for deterministic repair rules.

This is intentionally small. It only performs safe edits that do not require
semantic guessing. Unsupported actions fail closed and must be handled by the
Repair Agent fallback policy.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from common import load_json

IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w\.]+(?:\.\*)?)\s*;\n?", re.MULTILINE)
PACKAGE_RE = re.compile(r"^\s*package\s+[\w\.]+\s*;\s*\n", re.MULTILINE)


def is_import_allowed(fqcn: str, whitelist: dict) -> bool:
    target = fqcn.replace("static ", "")
    classes = {c.get("fqcn") for c in whitelist.get("classes", [])}
    packages = {p.get("name") for p in whitelist.get("packages", [])}
    if target in classes:
        return True
    owner = target.rsplit(".", 1)[0]
    return owner in packages


def add_import(text: str, imp: str, whitelist: dict) -> tuple[str, str | None]:
    if not is_import_allowed(imp, whitelist):
        return text, f"IMPORT_NOT_WHITELISTED: {imp}"
    line = f"import {imp};\n" if not imp.startswith("static ") else f"import static {imp[len('static '):]};\n"
    if line.strip() in {m.group(0).strip() for m in IMPORT_RE.finditer(text)}:
        return text, None
    imports = list(IMPORT_RE.finditer(text))
    if imports:
        pos = imports[-1].end()
        return text[:pos] + line + text[pos:], None
    pkg = PACKAGE_RE.search(text)
    if pkg:
        return text[:pkg.end()] + "\n" + line + text[pkg.end():], None
    return line + text, None


def remove_import(text: str, imp: str) -> str:
    escaped = re.escape(imp)
    return re.sub(rf"^\s*import\s+(?:static\s+)?{escaped}\s*;\s*\n", "", text, flags=re.MULTILINE)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--action", required=True, choices=["addImport", "removeImport"])
    ap.add_argument("--arg", required=True)
    ap.add_argument("--whitelist", required=True)
    args = ap.parse_args()

    path = Path(args.file)
    whitelist = load_json(Path(args.whitelist))
    text = path.read_text(encoding="utf-8", errors="ignore")
    if args.action == "addImport":
        new_text, err = add_import(text, args.arg, whitelist)
        if err:
            print(json.dumps({"status": "BLOCKED", "reason": err}, indent=2))
            return 1
    else:
        new_text = remove_import(text, args.arg)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
    print(json.dumps({"status": "OK", "changed": new_text != text}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
