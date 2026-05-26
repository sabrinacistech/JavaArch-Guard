"""context_pack_builder.py — Build minimal per-SUT context packs for LLM agents.

Reads state/batch-plan.json and, for each planned SUT, performs a surgical extraction
from the JSON state layer (stack-profile, classification-index, dependency-graph,
fixture-catalog, symbol-contracts, coverage-targets, import-whitelist).

Writes one compact JSON per SUT to: state/context-packs/<safe_fqcn>.json

The context-pack is the ONLY artifact LLM agents are allowed to consume.
No agent may open raw source code, pom.xml, build.gradle, or jacoco.xml.

Step 16 in run_pipeline.py  (--skip context).

Usage:
    python context_pack_builder.py --out state/
    python context_pack_builder.py --out state/ --sut com.example.MyService
    python context_pack_builder.py --out state/ --dry-run
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import atomic_write_json, fail, load_json, validate  # noqa: E402

SCHEMA_NAME = "context-pack"

FORBIDDEN_ACTIONS = [
    "READ_SOURCE_CODE",
    "READ_POM",
    "READ_JACOCO_XML",
    "READ_CLASSPATH",
    "READ_BYTECODE",
    "INVENT_SYMBOL",
    "INVENT_IMPORT",
    "RETURN_RAW_JAVA",
    "CALL_UNLISTED_METHOD",
    "INSTANTIATE_UNLISTED_TYPE",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_fqcn(fqcn: str) -> str:
    """Convert FQCN to a filesystem-safe filename stem."""
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", fqcn)


def load_optional(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return load_json(path)
    except Exception as exc:
        print(f"[WARN] Could not load {path}: {exc}", file=sys.stderr)
        return None


# ── Extractors ────────────────────────────────────────────────────────────────

def extract_stack(stack_profile: dict | None) -> tuple[dict, bool, str | None]:
    """Build minimal stack block from stack-profile.json; return (stack, blocked, reason).

    Blocked when the profile is absent or lacks at least one module with confirmed
    test.framework and mock.framework — no framework defaults are ever assumed.
    """
    _MISSING: dict = {
        "javaVersion": "unknown",
        "testFramework": "unknown",
        "mockFramework": "unknown",
    }

    if not stack_profile:
        return _MISSING, True, "stack-profile missing or incomplete"

    modules = stack_profile.get("modules", [])
    if not modules:
        return _MISSING, True, "stack-profile missing or incomplete"

    mod = modules[0]
    test_info = mod.get("test", {})
    mock_info = mod.get("mock", {})

    # A module without explicit framework values is treated as incomplete.
    if not test_info.get("framework") or not mock_info.get("framework"):
        return _MISSING, True, "stack-profile missing or incomplete"

    assert_info = mod.get("assert", {})
    di_info = mod.get("di", {})

    stack: dict = {
        "javaVersion": stack_profile.get("java", "unknown"),
        "testFramework": test_info.get("framework", "unknown"),
        "mockFramework": mock_info.get("framework", "unknown"),
    }

    test_version = test_info.get("version", "")
    if test_version:
        stack["testVersion"] = test_version

    mock_version = mock_info.get("version", "")
    if mock_version:
        stack["mockVersion"] = mock_version

    assert_framework = assert_info.get("framework")
    stack["assertFramework"] = assert_framework if assert_framework else "none"

    spring = bool(di_info.get("spring", False))
    stack["springEnabled"] = spring
    if spring:
        stack["springBootVersion"] = di_info.get("springBoot")
        slices = di_info.get("slices", [])
        if slices:
            stack["springSlices"] = slices

    namespace = _detect_namespace(stack_profile)
    stack["namespaceStyle"] = namespace

    processors = mod.get("annotationProcessors", [])
    if processors:
        stack["annotationProcessors"] = processors

    return stack, False, None


def _detect_namespace(stack_profile: dict) -> str:
    processors = []
    for mod in stack_profile.get("modules", []):
        processors.extend(mod.get("annotationProcessors", []))
    joined = " ".join(processors).lower()
    if "jakarta" in joined:
        return "jakarta"
    if "javax" in joined:
        return "javax"
    return "none"


def extract_classification(classification_index: dict | None, fqcn: str) -> dict:
    if not classification_index:
        return {}
    for entry in classification_index.get("classes", []):
        if entry.get("fqcn") == fqcn:
            result: dict = {}
            # Include each atomic field only when the value is present (not None).
            # Exception: recommendedTemplate accepts null in the schema → always include.
            for key in (
                "type", "testabilityRisk", "coverageValue", "reasons",
                "tags", "loc", "publicMethods", "cyclomatic", "coverage",
                "risk", "score",
            ):
                val = entry.get(key)
                if val is not None:
                    result[key] = val
            result["recommendedTemplate"] = entry.get("recommendedTemplate")
            return result
    return {}


def extract_coverage(coverage_targets: dict | None, sut: str, batch_items: list[dict]) -> dict:
    """Build coverage block: aggregate totals + per-target detail for this SUT."""
    sut_target_ids = {item["targetId"] for item in batch_items if item["sut"] == sut}
    targets_out: list[dict] = []
    total_lines = 0
    total_branches = 0

    if coverage_targets:
        for t in coverage_targets.get("targets", []):
            if t.get("sut") == sut and t.get("id") in sut_target_ids:
                ml = t.get("missedLines", 0)
                mb = t.get("missedBranches", 0)
                total_lines += ml
                total_branches += mb
                targets_out.append({
                    "targetId": t["id"],
                    "method": t.get("method", ""),
                    "missedLines": ml,
                    "missedBranches": mb,
                    "branchId": t.get("branchId", None),
                    "score": t.get("score"),
                })

    return {
        "totalMissedLines": total_lines,
        "totalMissedBranches": total_branches,
        "targets": targets_out,
    }


def extract_symbol_contract(
    symbol_contracts_dir: Path,
    fqcn: str,
) -> tuple[list[dict], list[dict]]:
    """Return (constructors, methods) from per-FQCN contract file."""
    contract_path = symbol_contracts_dir / f"{safe_fqcn(fqcn)}.json"
    contract = load_optional(contract_path)
    if not contract:
        return [], []

    constructors = [
        {
            "evidenceId": c["evidenceId"],
            "visibility": c.get("visibility", "public"),
            "params": c.get("params", []),
            "throws": c.get("throws", []),
        }
        for c in contract.get("constructors", [])
    ]

    methods = [
        {
            "evidenceId": m["evidenceId"],
            "name": m["name"],
            "returnType": m.get("returnType", "void"),
            "params": m.get("params", []),
            "throws": m.get("throws", []),
            "usable": bool(m.get("usable", True)),
        }
        for m in contract.get("methods", [])
        if m.get("usable", True)
    ]

    return constructors, methods


def extract_dependencies(dependency_graph: dict | None, fqcn: str) -> tuple[list, list, dict]:
    """Return (dependencies, collaboratorUsage, springStrategy) for this SUT."""
    if not dependency_graph:
        return [], [], {}

    for graph in dependency_graph.get("graphs", []):
        if graph.get("sut") == fqcn:
            deps = [
                {
                    "name": d["name"],
                    "type": d["type"],
                    "injection": d["injection"],
                    "final": d.get("final", False),
                }
                for d in graph.get("dependencies", [])
            ]
            collab = graph.get("collaboratorUsage", [])
            spring = graph.get("springStrategy", {})
            return deps, collab, spring

    return [], [], {}


def enrich_deps_with_strategy(
    dependencies: list[dict],
    fixture_catalog: dict | None,
) -> list[dict]:
    """Attach instantiationStrategy from fixture-catalog to each dependency."""
    if not fixture_catalog:
        return dependencies

    type_to_strategy: dict[str, str] = {
        f["type"]: f["strategy"]
        for f in fixture_catalog.get("fixtures", [])
    }

    enriched = []
    for dep in dependencies:
        d = dict(dep)
        d["instantiationStrategy"] = type_to_strategy.get(dep["type"], "mock")
        enriched.append(d)
    return enriched


def extract_fixtures(
    fixture_catalog: dict | None,
    dependencies: list[dict],
    batch_items: list[dict],
    sut: str,
) -> list[dict]:
    """Extract fixtures relevant to this SUT's dependencies and batch fixture IDs."""
    if not fixture_catalog:
        return []

    dep_types = {d["type"] for d in dependencies}
    batch_fixture_ids: set[str] = set()
    for item in batch_items:
        if item["sut"] == sut:
            batch_fixture_ids.update(item.get("fixtureIds", []))

    relevant: list[dict] = []
    for fix in fixture_catalog.get("fixtures", []):
        if fix["type"] in dep_types or fix["id"] in batch_fixture_ids:
            relevant.append({
                "id": fix["id"],
                "type": fix["type"],
                "strategy": fix["strategy"],
                "builderEvidence": fix.get("builderEvidence"),
                "constructorEvidence": fix.get("constructorEvidence"),
                "factoryEvidence": fix.get("factoryEvidence"),
                "values": fix.get("values", {}),
                "variants": fix.get("variants", []),
                "cycleSafe": fix.get("cycleSafe", True),
            })
    return relevant


def _framework_imports_from_stack(stack: dict) -> set[str]:
    """Map confirmed stack capabilities to allowed import FQCNs (minimum privilege).

    No framework package is included unless its corresponding stack flag is
    explicitly confirmed — 'unknown' or 'none' values contribute nothing.
    """
    imports: set[str] = set()

    test_fw = stack.get("testFramework", "unknown")
    mock_fw = stack.get("mockFramework", "unknown")
    assert_fw = stack.get("assertFramework", "unknown")
    spring = bool(stack.get("springEnabled", False))

    if test_fw == "junit5":
        imports.update({
            "org.junit.jupiter.api.Test",
            "org.junit.jupiter.api.BeforeEach",
            "org.junit.jupiter.api.AfterEach",
            "org.junit.jupiter.api.Assertions",
            "org.junit.jupiter.api.extension.ExtendWith",
        })
    elif test_fw == "junit4":
        imports.update({
            "org.junit.Test",
            "org.junit.Before",
            "org.junit.After",
        })

    if mock_fw == "mockito":
        imports.update({
            "org.mockito.Mockito",
            "org.mockito.Mock",
            "org.mockito.InjectMocks",
        })
        if test_fw == "junit5":
            imports.add("org.mockito.junit.jupiter.MockitoExtension")
        elif test_fw == "junit4":
            imports.add("org.mockito.junit.MockitoJUnitRunner")

    if assert_fw == "assertj":
        imports.add("org.assertj.core.api.Assertions")
    elif assert_fw == "hamcrest":
        imports.update({
            "org.hamcrest.MatcherAssert",
            "org.hamcrest.Matchers",
        })

    if spring:
        imports.update({
            "org.springframework.boot.test.context.SpringBootTest",
            "org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest",
            "org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest",
            "org.springframework.boot.test.mock.mockito.MockBean",
            "org.springframework.test.web.servlet.MockMvc",
            "org.springframework.beans.factory.annotation.Autowired",
        })

    return imports


def extract_allowed_imports(
    import_whitelist: dict | None,
    stack: dict,
    baseline_presets: list[str] | None = None,
) -> list[str]:
    """Return allowed FQCNs under minimum-privilege: stack-confirmed frameworks + whitelist.

    JDK standard-library classes (java.util.*, java.time.*, java.math.*, …) are
    admitted only when they appear explicitly in import-whitelist.json with origin
    'jdk', or when listed in the architecture baseline presets (stack_profile
    presets.imports.allowed).  They are never added unconditionally.
    """
    allowed: set[str] = _framework_imports_from_stack(stack)

    # Project-local (source/dep) and explicitly approved JDK classes from the whitelist.
    if import_whitelist:
        for entry in import_whitelist.get("classes", []):
            origin = entry.get("origin", "")
            fqcn = entry.get("fqcn", "")
            if fqcn and origin in ("source", "dep", "jdk"):
                allowed.add(fqcn)

    # Global exception rules parsed from the architecture baseline configuration
    # (stack_profile.presets.imports.allowed).
    if baseline_presets:
        allowed.update(baseline_presets)

    return sorted(allowed)


# ── Pack builder ──────────────────────────────────────────────────────────────

def build_pack(
    fqcn: str,
    mode: str,
    batch_items: list[dict],
    stack_profile: dict | None,
    classification_index: dict | None,
    dependency_graph: dict | None,
    fixture_catalog: dict | None,
    coverage_targets: dict | None,
    import_whitelist: dict | None,
    symbol_contracts_dir: Path,
) -> dict:
    """Assemble the minimal context-pack for one SUT."""
    stack, blocked, block_reason = extract_stack(stack_profile)
    classification = extract_classification(classification_index, fqcn)
    coverage = extract_coverage(coverage_targets, fqcn, batch_items)
    constructors, methods = extract_symbol_contract(symbol_contracts_dir, fqcn)
    deps_raw, collab_usage, spring_strategy = extract_dependencies(dependency_graph, fqcn)
    dependencies = enrich_deps_with_strategy(deps_raw, fixture_catalog)
    fixtures = extract_fixtures(fixture_catalog, deps_raw, batch_items, fqcn)

    baseline_presets: list[str] | None = None
    if stack_profile:
        raw_presets = stack_profile.get("presets", {}).get("imports.allowed")
        if isinstance(raw_presets, list):
            baseline_presets = raw_presets or None

    allowed_imports = extract_allowed_imports(import_whitelist, stack, baseline_presets)

    pack: dict = {
        "schemaVersion": 1,
        "sut": fqcn,
        "mode": mode,
        "stack": stack,
        "coverage": coverage,
        "constructors": constructors,
        "methods": methods,
        "dependencies": dependencies,
        "collaboratorUsage": collab_usage,
        "fixtures": fixtures,
        "allowedImports": allowed_imports,
        "forbidden": FORBIDDEN_ACTIONS,
    }

    if blocked:
        pack["blocked"] = True
        pack["blockReason"] = block_reason

    if classification:
        pack["classification"] = classification

    if spring_strategy:
        pack["springStrategy"] = spring_strategy

    return pack


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Build per-SUT context packs from the JSON state layer.\n"
            "Output: state/context-packs/<safe_fqcn>.json\n"
            "These packs are the ONLY JSON the LLM agents may read."
        )
    )
    ap.add_argument(
        "--out",
        required=True,
        help="State directory (contains batch-plan.json and other state files)",
    )
    ap.add_argument(
        "--sut",
        default=None,
        help="Build pack for a single FQCN only (default: all SUTs in batch-plan.json)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print each pack to stdout instead of writing files",
    )
    args = ap.parse_args()

    state_dir = Path(args.out).resolve()
    packs_dir = state_dir / "context-packs"
    contracts_dir = state_dir / "symbol-contracts"

    # ── Load batch plan (required) ────────────────────────────────────────────
    batch_plan_path = state_dir / "batch-plan.json"
    if not batch_plan_path.exists():
        fail(f"batch-plan.json not found in {state_dir} — run coverage_planner.py first")
    batch_plan = load_json(batch_plan_path)
    mode: str = batch_plan.get("mode", "coverage")
    batch_items: list[dict] = batch_plan.get("items", [])

    # ── Collect unique SUTs ───────────────────────────────────────────────────
    if args.sut:
        suts = [args.sut]
    else:
        seen: dict[str, bool] = {}
        suts = [
            seen.setdefault(item["sut"], item["sut"])  # type: ignore[func-returns-value]
            for item in batch_items
            if item["sut"] not in seen
        ]
        suts = list(seen.keys())

    if not suts:
        print("[INFO] No SUTs found in batch-plan.json — nothing to build.", file=sys.stderr)
        return 0

    # ── Load shared state files (optional — warn but don't fail) ─────────────
    stack_profile = load_optional(state_dir / "stack-profile.json")
    classification_index = load_optional(state_dir / "classification-index.json")
    dependency_graph = load_optional(state_dir / "dependency-graph.json")
    fixture_catalog = load_optional(state_dir / "fixture-catalog.json")
    coverage_targets = load_optional(state_dir / "coverage-targets.json")
    import_whitelist = load_optional(state_dir / "import-whitelist.json")

    if not stack_profile:
        print("[WARN] stack-profile.json missing — context packs will be marked blocked", file=sys.stderr)

    # ── Build and write one pack per SUT ─────────────────────────────────────
    errors = 0
    packs_dir.mkdir(parents=True, exist_ok=True)

    for fqcn in suts:
        try:
            pack = build_pack(
                fqcn=fqcn,
                mode=mode,
                batch_items=batch_items,
                stack_profile=stack_profile,
                classification_index=classification_index,
                dependency_graph=dependency_graph,
                fixture_catalog=fixture_catalog,
                coverage_targets=coverage_targets,
                import_whitelist=import_whitelist,
                symbol_contracts_dir=contracts_dir,
            )
        except Exception as exc:
            print(f"[ERROR] Building pack for {fqcn}: {exc}", file=sys.stderr)
            errors += 1
            continue

        try:
            validate(SCHEMA_NAME, pack)
        except Exception as exc:
            print(f"[WARN] Schema validation failed for {fqcn}: {exc}", file=sys.stderr)

        if args.dry_run:
            import json
            print(f"\n=== context-pack: {fqcn} ===")
            print(json.dumps(pack, ensure_ascii=False, indent=2))
        else:
            out_path = packs_dir / f"{safe_fqcn(fqcn)}.json"
            atomic_write_json(out_path, pack)
            print(f"[OK] {fqcn} → {out_path.relative_to(state_dir.parent)}")

    if errors:
        print(f"\n[FAIL] {errors} pack(s) failed to build.", file=sys.stderr)
        return 1

    print(f"\n[DONE] {len(suts)} context pack(s) written to {packs_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
