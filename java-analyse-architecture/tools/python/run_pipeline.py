"""run_pipeline.py — orchestrate the deterministic Python pre-stage.

Runs (in order):
   1. pom_parser                → state/build-tool-contract.json
   2. archetype_detector        → state/archetype-profile.json
   3. generated_code_scanner    → state/generated-code-index.json
   4. classpath_resolver        → state/import-whitelist.json
   5. stack_profile_detector    → state/stack-profile.json
   6. bytecode_scanner          → state/symbol-contracts/<fqcn>.json  (if --module)
   7. source_symbol_enricher    → enrich contracts (FreeBuilder/Lombok source-only semantics)
   8. jacoco_parser (targets)   → state/coverage-targets.json         (if --jacoco-xml)
   9. semantic_index_writer     → state/index/{classes,methods,imports,dependencies,annotations}.json
  10. classification_analyzer   → state/classification-index.json
  11. dependency_graph_extractor→ state/dependency-graph.json
  12. fixture_catalog_builder   → state/fixture-catalog.json
  13. coverage_planner          → state/batch-plan.json
  14. incremental_map_writer    → state/incremental-map.json           (if --since)
  15. state_validator           → validates all state/*.json
  16. context_pack_builder      → state/context-packs/<safe_fqcn>.json (one per SUT in batch)

After this, the LLM only consumes state/context-packs/*.json.  Token consumption drops
because no agent re-parses POMs, classpath, javap output or JaCoCo XML.  The context-pack
is the single source of truth for LLM agents — raw source code is NEVER passed to them.

Phase 1 (semantic index): step 9 projects all prior state into state/index/ so agents
query a single consistent index instead of re-reading raw sources, eliminating
O(agents × files) redundant reads.

Phase 2 (graph + fixtures + plan): steps 11-13 build the dependency graph, fixture
catalog, and ranked batch plan deterministically — without LLM.

Phase 3 (incremental): step 14 computes changed/affected scope from git diff when
--since is provided; the orchestrator uses this to narrow compilation and JaCoCo runs.

Skip names for --skip flag
--------------------------
  pom            step  1
  archetype      step  2
  generated      step  3
  classpath      step  4
  stack          step  5
  bytecode       step  6  (also skipped automatically when --module is absent)
  source         step  7
  jacoco         step  8  (also skipped automatically when --jacoco-xml is absent)
  index          step  9
  classification step 10
  deps           step 11
  fixtures       step 12
  planning       step 13
  incremental    step 14  (also skipped automatically when --since is absent)
  validate       step 15
  context        step 16  (builds state/context-packs/ — the LLM's only input)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run_step(args: list[str]) -> int:
    print(f"\n$ python {' '.join(str(a) for a in args)}")
    return subprocess.call([sys.executable, *[str(a) for a in args]])


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Run the deterministic Python pre-stage for the Java test-coverage architecture.\n"
            "After completion, all state/*.json files are ready for LLM agents to consume.\n"
            "No agent needs to re-parse POMs, classpaths, javap output or JaCoCo XML."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--repo",
        required=True,
        help="Root of the Java repository to analyse (must contain pom.xml)",
    )
    ap.add_argument(
        "--out",
        required=True,
        help="State directory where all JSON files will be written (e.g. state/)",
    )
    ap.add_argument(
        "--module",
        default=None,
        help="Restrict bytecode scan and classpath resolution to one module name",
    )
    ap.add_argument(
        "--include-fqcn",
        default=".*",
        help="Regex filter for bytecode scanner: only scan FQCNs matching this pattern "
             "(default: .* — all classes)",
    )
    ap.add_argument(
        "--jacoco-xml",
        default=None,
        help="Path to a JaCoCo jacoco.xml report.  When provided, step 8 runs and "
             "state/coverage-targets.json is populated.",
    )
    ap.add_argument(
        "--coverage-mode",
        default="coverage",
        choices=["coverage", "branch-coverage", "mutation-hardening"],
        help="Coverage scoring mode for jacoco_parser (default: coverage)",
    )
    ap.add_argument(
        "--since",
        default=None,
        help="Git ref (commit/branch/tag) to compute incremental scope from "
             "(e.g. HEAD~1, main).  When provided, step 11 runs and "
             "state/incremental-map.json is populated.",
    )
    ap.add_argument(
        "--full-index",
        action="store_true",
        help="Force full semantic index rebuild even if fingerprints match (step 9)",
    )
    ap.add_argument(
        "--skip",
        nargs="*",
        default=[],
        metavar="STEP",
        help=(
            "Step names to skip (space-separated).  Valid names:\n"
            "  pom, archetype, generated, classpath, stack, bytecode,\n"
            "  source, jacoco, index, classification, deps, fixtures,\n"
            "  planning, incremental, validate, context"
        ),
    )
    args = ap.parse_args()

    skip: set[str] = set(args.skip or [])
    rc = 0

    # ── Step 1: POM / build-tool contract ────────────────────────────────────
    if "pom" not in skip:
        rc |= run_step([HERE / "pom_parser.py", "--repo", args.repo, "--out", args.out])

    # ── Step 2: Archetype detection ───────────────────────────────────────────
    if "archetype" not in skip:
        rc |= run_step([HERE / "archetype_detector.py", "--repo", args.repo, "--out", args.out])

    # ── Step 3: Generated code scanner ───────────────────────────────────────
    if "generated" not in skip:
        rc |= run_step([
            HERE / "generated_code_scanner.py", "--repo", args.repo, "--out", args.out,
        ])

    # ── Step 4: Classpath resolver → import-whitelist.json ───────────────────
    if "classpath" not in skip:
        cp_args = [HERE / "classpath_resolver.py", "--repo", args.repo, "--out", args.out]
        if args.module:
            cp_args += ["--module", args.module]
        rc |= run_step(cp_args)

    # ── Step 5: Stack profile detector → stack-profile.json ──────────────────
    # Detects JUnit 4/5, Mockito, AssertJ, Spring, Testcontainers, annotation
    # processors, and javax vs jakarta namespace — all from pom.xml(s).
    if "stack" not in skip:
        rc |= run_step([
            HERE / "stack_profile_detector.py", "--repo", args.repo, "--out", args.out,
        ])

    # ── Step 6: Bytecode scanner → symbol-contracts/<fqcn>.json ─────────────
    # Only runs when --module is specified; without it there's no
    # target/classes to scan.
    if "bytecode" not in skip and args.module:
        rc |= run_step([
            HERE / "bytecode_scanner.py",
            "--repo", args.repo, "--out", args.out,
            "--module", args.module, "--include", args.include_fqcn,
        ])

    # ── Step 7: Source symbol enricher (FreeBuilder, Lombok, etc.) ───────────
    if "source" not in skip:
        source_args = [
            HERE / "source_symbol_enricher.py", "--repo", args.repo, "--out", args.out,
        ]
        if args.module:
            source_args += ["--module", args.module]
        rc |= run_step(source_args)

    # ── Step 8: JaCoCo parser → coverage-targets.json ────────────────────────
    # Only runs when --jacoco-xml is provided.
    if "jacoco" not in skip and args.jacoco_xml:
        rc |= run_step([
            HERE / "jacoco_parser.py",
            "--mode", "targets",
            "--xml", args.jacoco_xml,
            "--out", str(Path(args.out) / "coverage-targets.json"),
            "--coverage-mode", args.coverage_mode,
        ])

    # ── Step 9 [Phase 1]: Semantic index writer ───────────────────────────────
    # Projects all prior state into state/index/ — eliminates O(agents×files) reads.
    if "index" not in skip:
        idx_args = [HERE / "semantic_index_writer.py", "--out", args.out]
        if args.full_index:
            idx_args.append("--full")
        rc |= run_step(idx_args)

    # ── Step 10: Classification analyzer → classification-index.json ──────────
    # Static, LLM-free classification: @RestController → controller, etc.
    # Runs AFTER semantic_index_writer so state/index/ is populated.
    if "classification" not in skip:
        rc |= run_step([HERE / "classification_analyzer.py", "--out", args.out])

    # ── Step 11 [Phase 2]: Dependency graph extractor → dependency-graph.json ─
    # Maps constructor params → dependencies; marks interfaces as mockable.
    # Evidence-only: no types, constructors or field names are invented.
    if "deps" not in skip:
        rc |= run_step([HERE / "dependency_graph_extractor.py", "--out", args.out])

    # ── Step 12 [Phase 2]: Fixture catalog builder → fixture-catalog.json ─────
    # Assigns an instantiation strategy (builder/constructor/factory/mock/none)
    # for every SUT based solely on evidenced contract data.
    if "fixtures" not in skip:
        rc |= run_step([HERE / "fixture_catalog_builder.py", "--out", args.out])

    # ── Step 13 [Phase 2]: Coverage planner → batch-plan.json ────────────────
    # Ranks coverage targets by scoring formula; produces a compact batch plan.
    # Uses coverage-targets, classification, failure-memory and incremental-map.
    if "planning" not in skip:
        plan_args = [
            HERE / "coverage_planner.py",
            "--out", args.out,
            "--mode", args.coverage_mode,
        ]
        rc |= run_step(plan_args)

    # ── Step 14 [Phase 3]: Incremental map writer ─────────────────────────────
    # Computes changedFiles → affectedClasses → affectedTests from git diff.
    # Only runs when --since is supplied (skipped in CI full runs by default).
    if "incremental" not in skip and args.since:
        inc_args = [
            HERE / "incremental_map_writer.py",
            "--repo", args.repo,
            "--out", args.out,
            "--since", args.since,
        ]
        if args.module:
            inc_args += ["--module", args.module]
        rc |= run_step(inc_args)

    # ── Step 15: State validator ──────────────────────────────────────────────
    if "validate" not in skip:
        rc |= run_step([HERE / "state_validator.py", "--state", args.out])

    # ── Step 16: Context pack builder → state/context-packs/<safe_fqcn>.json ─
    # Produces one minimal JSON per SUT from the batch plan.  This is the ONLY
    # artifact LLM agents (test-intent, test-body, repair, report) may consume.
    # No agent reads raw source code, POM, classpath, bytecode or JaCoCo XML.
    if "context" not in skip:
        rc |= run_step([HERE / "context_pack_builder.py", "--out", args.out])

    print("\nDone." if rc == 0 else "\nDone with errors.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
