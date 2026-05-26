"""state_validator.py — validate state/*.json against state/_schemas/*.schema.json.

Correcciones implementadas:

  1. Acepta tanto --state como --state-dir (alias). Si se pasan ambos,
     --state-dir tiene prioridad y se emite un warning.

  2. symbol-contract.schema.json valida state/symbol-contracts/*.json
     (uno por FQCN), NO state/symbol-contract.json (que no existe y no
     debe existir). El manifest state/symbol-contracts.json se trata como
     estado auxiliar.

  3. context-pack.schema.json valida state/context-packs/*.json
     (uno por SUT), NO state/context-pack.json (que no existe y no
     debe existir).

  4. Archivos state/*.json sin schema asociado se reportan como
     [INFO] ... has no schema; treated as auxiliary state
     en lugar de quedar como estados ambiguos o silenciados.

  5. Archivos ausentes se tratan según su origen:
       - Escritos por el pipeline Python (steps 1-5, 9-10, siempre) → [ERR] si faltan.
       - Escritos condicionalmente por el pipeline Python            → [SKIP] con motivo.
       - Escritos por agentes LLM (fase posterior al pipeline)       → [SKIP] con motivo.
     Solo los archivos verdaderamente runtime/opcionales reciben [SKIP].

  6. Formato de salida estandarizado:
       [OK]   state/<file>.json                 — válido
       [SKIP] <name>.json — <motivo>            — ausente pero legítimamente opcional
       [INFO] state/<file>.json ...             — auxiliar sin schema, o directorio vacío
       [ERR]  state/<file>.json                 — inválido o faltante cuando era requerido
       [WARN] ...                               — advertencia no bloqueante
       [FAIL] ...                               — error fatal (dependencia faltante, etc.)

Usage:
    python tools/python/state_validator.py --state state
    python tools/python/state_validator.py --state-dir state
    python tools/python/state_validator.py --state state --state-dir state  # warn + use state-dir
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import SCHEMAS_DIR

# ---------------------------------------------------------------------------
# Schemas que NO se mapean a state/<name>.json sino que tienen lógica propia.
# ---------------------------------------------------------------------------
_SPECIAL_SCHEMAS: frozenset[str] = frozenset({
    "symbol-contract",  # → valida state/symbol-contracts/*.json
    "context-pack",     # → valida state/context-packs/*.json
})

# ---------------------------------------------------------------------------
# Estados runtime/opcionales: ausentes no es un error.
#
# Cada entrada mapea el nombre del schema (sin extensión) a la razón por la
# que su archivo de estado puede estar ausente legítimamente.
#
# Archivos NO listados aquí que tengan schema asociado son REQUERIDOS: el
# pipeline Python los escribe incondicionalmente y su ausencia es un [ERR].
# Actualmente eso corresponde a:
#   build-tool-contract  ← pom_parser.py              (Step  1)
#   archetype-profile    ← archetype_detector.py       (Step  2)
#   generated-code-index ← generated_code_scanner.py   (Step  3)
#   import-whitelist     ← classpath_resolver.py        (Step  4)
#   stack-profile        ← stack_profile_detector.py    (Step  5)
#   classification-index ← classification_analyzer.py   (Step 10)
# ---------------------------------------------------------------------------
_RUNTIME_OPTIONAL: dict[str, str] = {
    # ── Escritos por agentes LLM (fase posterior al pipeline Python) ──────────
    "compile-error-index":   "written by compile_error_parser when compilation fails",
    "coverage-summary":      "written by jacoco_parser after a JaCoCo run",
    "coverage-delta":        "written by jacoco_parser --mode delta (separate invocation)",
    "discovery-summary":     "written by LLM Discovery agent",
    "execution-state":       "written by LLM orchestrator",
    "failure-memory":        "written by LLM Repair agent across cycles",
    "generated-tests":       "written by LLM Generation agent",
    "mutation-intelligence": "written by LLM Mutation agent",
    # ── Escritos condicionalmente por el pipeline Python (flags opcionales) ───
    "coverage-targets":      "requires --jacoco-xml flag (Step 8)",
    "dependency-graph":      "requires pipeline Step 11; use --skip deps to omit",
    "fixture-catalog":       "requires pipeline Step 12; use --skip fixtures to omit",
    "batch-plan":            "requires pipeline Step 13; use --skip planning to omit",
    "incremental-map":       "requires --since flag (Step 14)",
}


# ---------------------------------------------------------------------------
# Helpers de validación de un único archivo
# ---------------------------------------------------------------------------

def _validate_file(
    target: Path,
    schema: dict,
    jsonschema,
) -> tuple[str, str | None]:
    """Valida `target` contra `schema`.

    Retorna ("OK", None) o ("ERR", mensaje).
    """
    try:
        with target.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        return "ERR", f"JSON inválido — {exc}"
    except OSError as exc:
        return "ERR", f"no se puede leer — {exc}"

    try:
        jsonschema.validate(data, schema)
        return "OK", None
    except jsonschema.ValidationError as exc:
        return "ERR", exc.message
    except jsonschema.SchemaError as exc:
        return "ERR", f"schema error — {exc.message}"


# ---------------------------------------------------------------------------
# Validación estándar: un schema → state/<name>.json
# ---------------------------------------------------------------------------

def validate_standard_schemas(
    schemas_dir: Path,
    state_dir: Path,
    jsonschema,
) -> int:
    """Valida state/<name>.json para cada *.schema.json (excepto los especiales).

    Retorna 0 si todo OK, 1 si al menos un archivo falla.
    """
    rc = 0
    for schema_file in sorted(schemas_dir.glob("*.schema.json")):
        name = schema_file.stem.replace(".schema", "")
        if name in _SPECIAL_SCHEMAS:
            continue   # manejado por validate_symbol_contracts()

        target = state_dir / f"{name}.json"
        if not target.exists():
            if name in _RUNTIME_OPTIONAL:
                print(f"[SKIP] {name}.json — {_RUNTIME_OPTIONAL[name]}")
            else:
                print(
                    f"[ERR]  state/{name}.json — missing; must be produced by the Python pipeline",
                    file=sys.stderr,
                )
                rc = 1
            continue

        try:
            with schema_file.open("r", encoding="utf-8") as fh:
                schema = json.load(fh)
        except Exception as exc:
            print(
                f"[ERR]  cannot load schema {schema_file.name}: {exc}",
                file=sys.stderr,
            )
            rc = 1
            continue

        status, error = _validate_file(target, schema, jsonschema)
        if status == "OK":
            print(f"[OK]   state/{target.name}")
        else:
            print(
                f"[ERR]  state/{target.name}\n"
                f"       schema: state/_schemas/{schema_file.name}\n"
                f"       reason: {error}",
                file=sys.stderr,
            )
            rc = 1

    return rc


# ---------------------------------------------------------------------------
# Validación especial: symbol-contract.schema.json → state/symbol-contracts/
# ---------------------------------------------------------------------------

def validate_symbol_contracts(
    schemas_dir: Path,
    state_dir: Path,
    jsonschema,
) -> int:
    """Valida cada state/symbol-contracts/<fqcn>.json contra symbol-contract.schema.json.

    - Si el directorio no existe o está vacío → [INFO], sin error.
    - Si existe algún contrato inválido → [ERR] con detalle, exit 1.
    - No toca state/symbol-contracts.json (manifest auxiliar, otro archivo).
    """
    schema_file = schemas_dir / "symbol-contract.schema.json"
    contracts_dir = state_dir / "symbol-contracts"

    if not schema_file.exists():
        print("[INFO] symbol-contract.schema.json not found; skipping contract validation")
        return 0

    if not contracts_dir.exists() or not contracts_dir.is_dir():
        print("[INFO] state/symbol-contracts/ directory not found; skipping contract validation")
        return 0

    contract_files = sorted(contracts_dir.glob("*.json"))
    if not contract_files:
        print("[INFO] state/symbol-contracts/ has no contract files yet")
        return 0

    try:
        with schema_file.open("r", encoding="utf-8") as fh:
            schema = json.load(fh)
    except Exception as exc:
        print(
            f"[ERR]  cannot load symbol-contract.schema.json: {exc}",
            file=sys.stderr,
        )
        return 1

    rc = 0
    ok_count = 0
    for cf in contract_files:
        status, error = _validate_file(cf, schema, jsonschema)
        if status == "OK":
            print(f"[OK]   state/symbol-contracts/{cf.name}")
            ok_count += 1
        else:
            print(
                f"[ERR]  state/symbol-contracts/{cf.name}\n"
                f"       schema: state/_schemas/symbol-contract.schema.json\n"
                f"       reason: {error}",
                file=sys.stderr,
            )
            rc = 1

    if ok_count > 0 and rc == 0:
        print(
            f"[OK]   state/symbol-contracts/ — {ok_count} contract(s) valid"
        )

    return rc


# ---------------------------------------------------------------------------
# Validación especial: context-pack.schema.json → state/context-packs/
# ---------------------------------------------------------------------------

def validate_context_packs(
    state_dir: Path,
    schemas_dir: Path,
    jsonschema,
) -> int:
    """Valida cada state/context-packs/<sut>.json contra context-pack.schema.json.

    - Si el directorio no existe o está vacío → [INFO], sin error (exit 0).
    - Si existe algún pack inválido → [ERR] con detalle, exit 1.
    - No lee state/context-pack.json; ese archivo singular no existe y no
      debe existir.
    """
    schema_file = schemas_dir / "context-pack.schema.json"
    context_packs_dir = state_dir / "context-packs"

    if not schema_file.exists():
        print("[INFO] context-pack.schema.json not found; skipping context-pack validation")
        return 0

    if not context_packs_dir.exists() or not context_packs_dir.is_dir():
        print("[INFO] state/context-packs/ has no context pack files yet")
        return 0

    pack_files = sorted(context_packs_dir.glob("*.json"))
    if not pack_files:
        print("[INFO] state/context-packs/ has no context pack files yet")
        return 0

    try:
        with schema_file.open("r", encoding="utf-8") as fh:
            schema = json.load(fh)
    except Exception as exc:
        print(
            f"[ERR]  cannot load context-pack.schema.json: {exc}",
            file=sys.stderr,
        )
        return 1

    rc = 0
    ok_count = 0
    for pf in pack_files:
        status, error = _validate_file(pf, schema, jsonschema)
        if status == "OK":
            print(f"[OK]   state/context-packs/{pf.name}")
            ok_count += 1
        else:
            print(
                f"[ERR]  state/context-packs/{pf.name}\n"
                f"       schema: state/_schemas/context-pack.schema.json\n"
                f"       reason: {error}",
                file=sys.stderr,
            )
            rc = 1

    if ok_count > 0 and rc == 0:
        print(f"[OK]   state/context-packs/ — {ok_count} context pack(s) valid")

    return rc


# ---------------------------------------------------------------------------
# Reporte de archivos auxiliares (sin schema)
# ---------------------------------------------------------------------------

def report_auxiliary_files(schemas_dir: Path, state_dir: Path) -> None:
    """Imprime [INFO] para state/*.json sin schema asociado.

    No emite error; solo informa que son estados auxiliares no validados.
    Ejemplos: symbol-contracts.json (manifest), module-progress.json, telemetry.json.
    """
    schema_stems = {
        sf.stem.replace(".schema", "")
        for sf in schemas_dir.glob("*.schema.json")
    }
    for jf in sorted(state_dir.glob("*.json")):
        stem = jf.stem
        if stem in schema_stems:
            # Ya validado (o en skip justificado) por validate_standard_schemas()
            continue
        print(
            f"[INFO] state/{jf.name} has no schema; treated as auxiliary state"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Validate state/*.json against state/_schemas/*.schema.json.\n"
            "Validates state/symbol-contracts/*.json against symbol-contract.schema.json."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--state",
        default=None,
        help="Path to the state directory (e.g. state/)",
    )
    ap.add_argument(
        "--state-dir",
        dest="state_dir",
        default=None,
        help="Alias for --state; takes priority over --state when both are given",
    )
    args = ap.parse_args()

    # ── Resolver directorio de estado ────────────────────────────────────────
    if args.state_dir and args.state:
        print(
            "[WARN] Both --state and --state-dir supplied; using --state-dir",
            file=sys.stderr,
        )
        raw_dir = args.state_dir
    elif args.state_dir:
        raw_dir = args.state_dir
    elif args.state:
        raw_dir = args.state
    else:
        ap.error("one of --state or --state-dir is required")
        return 2  # inalcanzable, pero calma a los type-checkers

    state_dir = Path(raw_dir).resolve()
    if not state_dir.exists():
        print(
            f"[FAIL] state directory not found: {state_dir}",
            file=sys.stderr,
        )
        return 2

    # ── Dependencia jsonschema ────────────────────────────────────────────────
    try:
        import jsonschema  # type: ignore
    except ImportError:
        print(
            "[FAIL] jsonschema not installed — run: pip install jsonschema",
            file=sys.stderr,
        )
        return 3

    rc = 0

    # ── 1. Validación estándar: schema → state/<name>.json ───────────────────
    rc |= validate_standard_schemas(SCHEMAS_DIR, state_dir, jsonschema)

    # ── 2. Validación especial: symbol-contracts/ ─────────────────────────────
    result = validate_symbol_contracts(SCHEMAS_DIR, state_dir, jsonschema)
    if result != 0:
        rc = result

    # ── 3. Validación especial: context-packs/ ────────────────────────────────
    result = validate_context_packs(state_dir, SCHEMAS_DIR, jsonschema)
    if result != 0:
        rc = result

    # ── 4. Archivos auxiliares sin schema ─────────────────────────────────────
    report_auxiliary_files(SCHEMAS_DIR, state_dir)

    return rc


if __name__ == "__main__":
    sys.exit(main())
