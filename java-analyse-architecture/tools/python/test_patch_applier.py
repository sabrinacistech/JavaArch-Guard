"""test_patch_applier.py — inject LLM-produced JSON patches into Java test files.

Applies structured JSON patch descriptors (from Body Agent or Repair Agent) onto
physical Java test files under authorized test directories only.

HARD CONSTRAINTS enforced here (not by the LLM):
  - NEVER touches src/main/java/** (PermissionError raised before any write).
  - Only writes to authorized test roots (src/test/java, src/integrationTest/java, etc.).
  - Template-initialized files are seeded from templates/<name>.java[.tpl].
  - Method-name collision detection prevents duplicate @Test methods.
  - Every injected method receives an // evidence: comment from evidenceIds[].
  - state/generated-tests.json is updated atomically after each patch.

Usage:
  python test_patch_applier.py \\
    --patch         state/_patches/FooServiceTest.patch.json \\
    --repo          /path/to/java-repo \\
    --state         state \\
    --templates     templates \\
    --context-pack  state/context-packs/<fqcn>.json \\
    --whitelist     state/import-whitelist.json \\
    --out           state/generated-tests.json \\
    [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import sys
import textwrap
import uuid
from pathlib import Path
from typing import Any

from common import atomic_write_json, load_json, validate

# ── Safety constants ─────────────────────────────────────────────────────────
_FORBIDDEN_SEGMENTS = ("src/main/java", "src\\main\\java")
_AUTHORIZED_TEST_ROOTS = (
    "src/test/java",
    "src/integrationTest/java",
    "src/integration-test/java",
    "src/testFixtures/java",
)

# ── Regex helpers ─────────────────────────────────────────────────────────────
_IMPORT_LINE_RE = re.compile(
    r"^\s*import\s+(static\s+)?[\w\.]+(?:\.\*)?\s*;", re.MULTILINE
)
_PACKAGE_RE = re.compile(r"^\s*package\s+[\w\.]+\s*;", re.MULTILINE)
_LAST_IMPORT_RE = re.compile(r"^import\s+[\w\.]+(?:\.\*)?\s*;", re.MULTILINE)
_FIELD_INJECT_RE = re.compile(r"^\s*@InjectMocks\b", re.MULTILINE)
_CLASS_OPEN_RE = re.compile(r"\bclass\s+\w+[^{]*\{", re.DOTALL)
_LAST_CLOSING_BRACE_RE = re.compile(r"^}", re.MULTILINE)
_METHOD_NAME_RE = re.compile(
    r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*"
    r"(?:(?:public|protected|private|static|final|synchronized|abstract)\s+)*"
    r"(?:void|[\w<>\[\]]+)\s+(\w+)\s*\(",
    re.MULTILINE,
)
_FIELD_NAME_RE = re.compile(
    r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*"
    r"(?:private|protected|public)\s+[\w<>\[\], ]+\s+(\w+)\s*[;=]",
    re.MULTILINE,
)
_COLLAB_BLOCK_RE = re.compile(
    r"[ \t]*//[ \t]*\$\{COLLABORATORS\}[^\n]*(?:\n[ \t]*//[^\n]*)*",
    re.MULTILINE,
)
_BODY_PLACEHOLDER_RE = re.compile(
    r"[ \t]*//[ \t]*\$\{TEST_BODY\}[^\n]*",
    re.MULTILINE,
)


# ── Import perimeter helpers ──────────────────────────────────────────────────

def _import_in_authorized_set(imp: str, authorized: set[str]) -> bool:
    """Return True if *imp* (a patch.allowedImports entry) is covered by *authorized*.

    *authorized* may contain: full FQCNs, package names, or "static X.Y.Z" entries.
    Matching rules (in order):
      1. Exact match (including "static X.Y.Z" entries from context-pack).
      2. Strip leading "static " and retry.
      3. Package prefix: "org.junit.jupiter.api" covers "org.junit.jupiter.api.Test".
      4. Wildcard: "org.junit.*" is covered if "org.junit" is in authorized.
    """
    if imp in authorized:
        return True
    bare = imp[len("static "):] if imp.startswith("static ") else imp
    if bare in authorized:
        return True
    if bare.endswith(".*"):
        return bare[:-2] in authorized
    if "." in bare:
        return bare.rsplit(".", 1)[0] in authorized
    return False


# ── Safety checks ─────────────────────────────────────────────────────────────

def _assert_not_production(path: Path, repo: Path) -> None:
    try:
        rel = path.relative_to(repo).as_posix()
    except ValueError:
        rel = str(path)
    for seg in _FORBIDDEN_SEGMENTS:
        if seg in rel:
            raise PermissionError(
                f"[BLOCKED] test_patch_applier must NEVER touch production code: {rel}"
            )


def _is_authorized_test_path(path: Path, repo: Path) -> bool:
    try:
        rel = path.relative_to(repo).as_posix()
    except ValueError:
        return False
    return any(rel.startswith(root) for root in _AUTHORIZED_TEST_ROOTS)


# ── Path resolution ────────────────────────────────────────────────────────────

def _resolve_test_file(patch: dict, repo: Path) -> Path:
    test_class: str = patch["testClass"]          # e.g. com.acme.FooServiceTest
    pkg_path = test_class.replace(".", "/") + ".java"
    target_dir: str = patch.get("targetDir") or "src/test/java"
    module: str = patch.get("targetModule") or ""
    if module:
        base = repo / module / target_dir / pkg_path
    else:
        base = repo / target_dir / pkg_path
    return base.resolve()


# ── Template loading ──────────────────────────────────────────────────────────

def _load_template(name: str, templates_dir: Path) -> str:
    for candidate in (
        templates_dir / f"{name}.java",
        templates_dir / f"{name}.java.tpl",
        templates_dir / "junit5-mockito.java",
    ):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"Template '{name}' not found in {templates_dir}. "
        "Expected file: <name>.java or <name>.java.tpl"
    )


# ── Code-generation helpers ───────────────────────────────────────────────────

def _indent_body(body: str) -> str:
    if not body.strip():
        return ""
    lines = textwrap.dedent(body).splitlines()
    out = []
    for line in lines:
        out.append(("        " + line.rstrip()) if line.strip() else "")
    return "\n".join(out)


def _render_method(m: dict) -> str:
    anns = m.get("annotations") or ["@Test"]
    ann_lines = "\n".join(f"    {a}" for a in anns)
    body_raw = (m.get("body") or "").strip()
    ev_ids = m.get("evidenceIds") or []
    if ev_ids and "// evidence:" not in body_raw:
        body_raw = body_raw + f"\n// evidence: {', '.join(ev_ids)}"
    indented = _indent_body(body_raw)
    return f"{ann_lines}\n    void {m['name']}() {{\n{indented}\n    }}"


def _field_declaration(f: dict) -> str:
    ann = f.get("annotation") or "@Mock"
    return f"    {ann}\n    private {f['type']} {f['name']};"


def _render_from_template(tpl: str, patch: dict) -> str:
    sut_fqn: str = patch["sut"]
    sut_simple = sut_fqn.rsplit(".", 1)[-1]
    pkg = patch.get("testPackage") or sut_fqn.rsplit(".", 1)[0]

    fields = patch.get("fields") or []
    methods = patch.get("methods") or []

    collab_block = (
        "\n\n".join(_field_declaration(f) for f in fields)
        if fields
        else "    // no collaborators"
    )
    body_block = (
        "\n\n".join(_render_method(m) for m in methods)
        if methods
        else "    // no test methods generated"
    )

    result = tpl
    result = result.replace("${PACKAGE}", pkg)
    result = result.replace("${SUT_SIMPLE}", sut_simple)
    result = result.replace("${SUT_FQN}", sut_fqn)
    result = _COLLAB_BLOCK_RE.sub(collab_block, result)
    result = _BODY_PLACEHOLDER_RE.sub("\n\n" + body_block, result)
    return result


# ── Extraction helpers ────────────────────────────────────────────────────────

def _existing_imports(text: str) -> set[str]:
    return {m.group(0).strip() for m in _IMPORT_LINE_RE.finditer(text)}


def _existing_method_names(text: str) -> set[str]:
    return {m.group(1) for m in _METHOD_NAME_RE.finditer(text)}


def _existing_field_names(text: str) -> set[str]:
    return {m.group(1) for m in _FIELD_NAME_RE.finditer(text)}


# ── Injection into existing files ─────────────────────────────────────────────

def _inject_imports(text: str, new_imports: list[str]) -> str:
    existing = _existing_imports(text)
    to_add = []
    for imp in new_imports:
        stmt = f"import {imp};"
        if stmt not in existing and f"import static {imp};" not in existing:
            to_add.append(stmt)
    if not to_add:
        return text
    matches = list(_LAST_IMPORT_RE.finditer(text))
    if matches:
        pos = matches[-1].end()
        return text[:pos] + "\n" + "\n".join(to_add) + text[pos:]
    pkg_m = _PACKAGE_RE.search(text)
    if pkg_m:
        pos = pkg_m.end()
        return text[:pos] + "\n\n" + "\n".join(to_add) + text[pos:]
    return "\n".join(to_add) + "\n\n" + text


def _inject_fields(text: str, fields: list[dict], existing_names: set[str]) -> str:
    to_add = [f for f in fields if f["name"] not in existing_names]
    if not to_add:
        return text
    block = "\n\n".join(_field_declaration(f) for f in to_add)
    inj_m = _FIELD_INJECT_RE.search(text)
    if inj_m:
        pos = inj_m.start()
        return text[:pos] + block + "\n\n    " + text[pos:]
    cls_m = _CLASS_OPEN_RE.search(text)
    if cls_m:
        pos = cls_m.end()
        return text[:pos] + "\n\n" + block + text[pos:]
    return text


def _inject_methods(text: str, methods: list[dict], existing_names: set[str]) -> str:
    to_add = [m for m in methods if m["name"] not in existing_names]
    if not to_add:
        return text
    blocks = "\n\n".join(_render_method(m) for m in to_add)
    last_brace = None
    for match in _LAST_CLOSING_BRACE_RE.finditer(text):
        last_brace = match
    if last_brace:
        pos = last_brace.start()
        return text[:pos] + "\n" + blocks + "\n\n" + text[pos:]
    return text + "\n\n" + blocks + "\n}\n"


# ── Core apply function ───────────────────────────────────────────────────────

def apply_patch(
    patch: dict,
    repo: Path,
    templates_dir: Path,
    dry_run: bool = False,
) -> dict:
    patch_id: str = patch.get("patchId") or f"patch:{uuid.uuid4().hex[:12]}"
    sut: str = patch["sut"]
    test_class: str = patch["testClass"]
    fields: list[dict] = patch.get("fields") or []
    methods: list[dict] = patch.get("methods") or []
    allowed_imports: list[str] = patch.get("allowedImports") or []

    test_path = _resolve_test_file(patch, repo)
    _assert_not_production(test_path, repo)

    if not _is_authorized_test_path(test_path, repo):
        rel = test_path.relative_to(repo).as_posix() if test_path.is_relative_to(repo) else str(test_path)
        raise PermissionError(
            f"[BLOCKED] Target path is not an authorized test directory: {rel}\n"
            f"Authorized roots: {_AUTHORIZED_TEST_ROOTS}"
        )

    injected_methods: list[str] = []
    skipped_methods: list[str] = []
    action: str

    if test_path.exists():
        current = test_path.read_text(encoding="utf-8")
        ex_methods = _existing_method_names(current)
        ex_fields = _existing_field_names(current)

        skipped_methods = [m["name"] for m in methods if m["name"] in ex_methods]
        injected_methods = [m["name"] for m in methods if m["name"] not in ex_methods]

        new_text = current
        new_text = _inject_imports(new_text, allowed_imports)
        new_text = _inject_fields(new_text, fields, ex_fields)
        new_text = _inject_methods(new_text, methods, ex_methods)
        action = "PATCHED"
    else:
        template_name: str = patch.get("template") or "junit5-mockito"
        tpl_src = _load_template(template_name, templates_dir)
        new_text = _render_from_template(tpl_src, patch)
        new_text = _inject_imports(new_text, allowed_imports)
        injected_methods = [m["name"] for m in methods]
        action = "INITIALIZED"

    if not dry_run:
        test_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = test_path.with_suffix(".java.tmp")
        tmp.write_text(new_text, encoding="utf-8")
        tmp.replace(test_path)

    return {
        "patchId": patch_id,
        "action": action,
        "testClass": test_class,
        "sut": sut,
        "file": str(test_path),
        "injectedMethods": injected_methods,
        "skippedMethods": skipped_methods,
        "status": "PROPOSED" if not dry_run else "DRY_RUN",
    }


# ── Report updater ────────────────────────────────────────────────────────────

def _update_report(
    out_path: Path,
    result: dict,
    patch: dict,
    dry_run: bool,
) -> None:
    if out_path.exists():
        report = load_json(out_path)
    else:
        report = {"schemaVersion": 1, "tests": []}

    cycle = patch.get("cycle", 1)
    all_evidence: list[str] = [
        eid
        for m in (patch.get("methods") or [])
        for eid in (m.get("evidenceIds") or [])
    ]
    new_entry: dict = {
        "testClass": result["testClass"],
        "sut": result["sut"],
        "status": result["status"],
        "patchId": result["patchId"],
        "evidenceIds": all_evidence,
    }
    report["cycle"] = cycle
    tests: list[dict] = report.setdefault("tests", [])
    existing = next(
        (t for t in tests if t["testClass"] == result["testClass"]),
        None,
    )
    if existing:
        existing.update(new_entry)
    else:
        tests.append(new_entry)

    if not dry_run:
        validate("generated-tests", report)
        atomic_write_json(out_path, report)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Apply a JSON patch descriptor from Body/Repair Agent onto a Java test file. "
            "Initializes from template if the file does not exist. "
            "NEVER modifies src/main/java."
        )
    )
    ap.add_argument(
        "--patch",
        required=True,
        metavar="PATH",
        help="JSON patch file produced by Body Agent or Repair Agent.",
    )
    ap.add_argument(
        "--repo",
        required=True,
        metavar="DIR",
        help="Root directory of the Java repository being tested.",
    )
    ap.add_argument(
        "--state",
        default="state",
        metavar="DIR",
        help="State directory (default: state/).",
    )
    ap.add_argument(
        "--templates",
        default=None,
        metavar="DIR",
        help=(
            "Templates directory. Defaults to <architecture-root>/templates/. "
            "Template files: <name>.java or <name>.java.tpl"
        ),
    )
    ap.add_argument(
        "--out",
        default=None,
        metavar="PATH",
        help="Output path for generated-tests.json (default: <state>/generated-tests.json).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Simulate the patch without writing any Java files. "
            "The generated-tests.json report is also NOT updated."
        ),
    )
    ap.add_argument(
        "--context-pack",
        default=None,
        metavar="PATH",
        help=(
            "Optional: path to state/context-packs/<fqcn>.json. "
            "When provided, (1) validates patch.allowedImports against "
            "contextPack.allowedImports and (2) asserts patch.sut == contextPack.sut. "
            "Any import absent from the authorized set causes exit 3."
        ),
    )
    ap.add_argument(
        "--whitelist",
        default=None,
        metavar="PATH",
        help=(
            "Optional: path to state/import-whitelist.json. "
            "When provided, validates patch.allowedImports against the whitelist's "
            "packages[] and classes[] entries. "
            "Any import absent from the authorized set causes exit 3."
        ),
    )
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    state_dir = Path(args.state) if Path(args.state).is_absolute() else Path.cwd() / args.state

    if args.templates:
        templates_dir = Path(args.templates).resolve()
    else:
        templates_dir = (Path(__file__).resolve().parents[2] / "templates").resolve()

    out_path = (
        Path(args.out).resolve()
        if args.out
        else (state_dir / "generated-tests.json").resolve()
    )

    patch_path = Path(args.patch)
    if not patch_path.exists():
        print(f"[FAIL] Patch file not found: {patch_path}", file=sys.stderr)
        return 2

    try:
        patch = load_json(patch_path)
    except Exception as exc:
        print(f"[FAIL] Cannot parse patch JSON: {exc}", file=sys.stderr)
        return 2

    required_keys = {"sut", "testClass"}
    missing = required_keys - patch.keys()
    if missing:
        print(
            f"[FAIL] Patch JSON missing required keys: {missing}",
            file=sys.stderr,
        )
        return 2

    # ── Perimeter interception middleware (runs before any I/O write) ─────────
    context_pack: dict | None = None
    if args.context_pack:
        try:
            context_pack = load_json(Path(args.context_pack).resolve())
        except Exception as exc:
            print(f"[FAIL] Cannot load context-pack: {exc}", file=sys.stderr)
            return 2
        # Structural SUT identity check
        cp_sut = context_pack.get("sut")
        patch_sut = patch.get("sut")
        if cp_sut != patch_sut:
            print(
                f"[BLOCKED] patch.sut '{patch_sut}' does not match "
                f"contextPack.sut '{cp_sut}'",
                file=sys.stderr,
            )
            return 3

    # Build authorized import set (union of context-pack + whitelist sources)
    authorized_imports: set[str] | None = None
    if context_pack is not None or args.whitelist:
        authorized_imports = set()
        if context_pack is not None:
            authorized_imports.update(context_pack.get("allowedImports") or [])
        if args.whitelist:
            try:
                wl = load_json(Path(args.whitelist).resolve())
            except Exception as exc:
                print(f"[FAIL] Cannot load whitelist: {exc}", file=sys.stderr)
                return 2
            authorized_imports.update(wl.get("packages") or [])
            authorized_imports.update(wl.get("classes") or [])

    # Validate every declared import against the authorized perimeter
    if authorized_imports is not None:
        for imp in (patch.get("allowedImports") or []):
            if not _import_in_authorized_set(imp, authorized_imports):
                print(
                    f"[BLOCKED] import not allowed by context-pack/whitelist: {imp}",
                    file=sys.stderr,
                )
                return 3
    # ── End perimeter middleware ───────────────────────────────────────────────

    try:
        result = apply_patch(patch, repo, templates_dir, dry_run=args.dry_run)
    except PermissionError as exc:
        print(f"[BLOCKED] {exc}", file=sys.stderr)
        return 3
    except FileNotFoundError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[FAIL] Unexpected error: {exc}", file=sys.stderr)
        return 1

    _update_report(out_path, result, patch, dry_run=args.dry_run)

    prefix = "[DRY-RUN] " if args.dry_run else ""
    print(
        f"{prefix}[{result['action']}] {result['testClass']}\n"
        f"  file:     {result['file']}\n"
        f"  injected: {result['injectedMethods']}\n"
        f"  skipped:  {result['skippedMethods']} (signature collision)\n"
        f"  patchId:  {result['patchId']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
