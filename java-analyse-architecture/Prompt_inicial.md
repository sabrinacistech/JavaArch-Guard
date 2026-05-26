<!-- ╔══════════════════════════════════════════════════════════════════╗
     ║  MODO DE USO — elige el bloque que corresponde a tu setup      ║
     ╠══════════════════════════════════════════════════════════════════╣
     ║  STANDALONE: VS Code abierto en java-test-coverage-architecture/║
     ║  EMBEBIDO:   arquitectura en docs/agents/java-test-coverage-    ║
     ║              architecture/ dentro de tu proyecto Java           ║
     ╚══════════════════════════════════════════════════════════════════╝ -->

<!-- ── STANDALONE (descomentar este bloque y borrar el de EMBEBIDO) ── -->
Actuá como el **Coverage Orchestrator** definido en `MASTER_PROMPT.md`.

Cargá y aplicá obligatoriamente:
- `MASTER_PROMPT.md`
- `agents/coverage-orchestrator.md`
- `docs/python-pipeline.md`
- `docs/performance-tuning.md`
- `docs/archetype-policy.md`
- Los skills de la fase activa bajo `skills/**`
- Los schemas bajo `state/_schemas/**`

<!-- ── EMBEBIDO (descomentar si la arquitectura está en docs/agents/...) ──
Actuá como el **Coverage Orchestrator** definido en
`docs/agents/java-test-coverage-architecture/MASTER_PROMPT.md`.

Cargá y aplicá obligatoriamente:
- `docs/agents/java-test-coverage-architecture/MASTER_PROMPT.md`
- `docs/agents/java-test-coverage-architecture/agents/coverage-orchestrator.md`
- `docs/agents/java-test-coverage-architecture/docs/python-pipeline.md`
- `docs/agents/java-test-coverage-architecture/docs/performance-tuning.md`
- `docs/agents/java-test-coverage-architecture/docs/archetype-policy.md`
- Los skills de la fase activa bajo `docs/agents/java-test-coverage-architecture/skills/**`
- Los schemas bajo `docs/agents/java-test-coverage-architecture/state/_schemas/**`
── -->

## Parámetros de ejecución
- repo: <ruta o "workspace actual">
- modules: <"all" | lista de módulos Maven/Gradle>
- mode: <coverage | branch-coverage | mutation-hardening>
- includeFqcn: <regex, ej. '^com\.acme\.'>
- budget:
    maxCycles: 10
    maxMinutesPerCycle: 10
- coverageGoal:
    lines: 0.80          # opcional
    branches: 0.60       # opcional
- writeTests: false      # true = escribe en src/test/java; false = solo propone

## Phase 0 — Python pre-stage (OBLIGATORIO antes de cualquier fase LLM)

Antes de actuar como Orchestrator, verificá que existan los `state/*.json` precomputados por el pipeline determinista. Si faltan, ejecutá (o pedí ejecutar):

```powershell
# ── Modo standalone (VS Code en java-test-coverage-architecture/) ──
mvn -q -DskipTests package   # ejecutar desde el repo Java
python tools/python/run_pipeline.py `
  --repo <ruta-al-repo-java> `
  --out state `
  --module <module> `
  --include-fqcn '<regex>' `
  --jacoco-xml <ruta-al-repo-java>/target/site/jacoco/jacoco.xml `
  --coverage-mode <coverage|branch-coverage|mutation-hardening>

# ── Modo embebido (arquitectura en docs/agents/java-test-coverage-architecture/) ──
# python docs/agents/java-test-coverage-architecture/tools/python/run_pipeline.py `
#   --repo . `
#   --out docs/agents/java-test-coverage-architecture/state `
#   --module <module> `
#   --include-fqcn '<regex>' `
#   --jacoco-xml target/site/jacoco/jacoco.xml `
#   --coverage-mode <coverage|branch-coverage|mutation-hardening>
```

Esto produce:
- `state/build-tool-contract.json`
- `state/archetype-profile.json`
- `state/generated-code-index.json`
- `state/import-whitelist.json`
- `state/symbol-contracts/<fqcn>.json`
- `state/coverage-targets.json` (si hay jacoco.xml)

**Si cualquiera de estos JSON falta o no valida contra su schema ⇒ abortar con `BLOCKED_PRE_STAGE_MISSING`.** No leas POMs, classpath crudo, `javap` ni `jacoco.xml` directamente: consumí solo los JSON.

## Reglas duras
1. No inventes paquetes, clases, métodos, builders, setters, constructors ni imports.
2. Toda línea de cada test propuesto debe citar un `evidence-id` del contrato.
3. Aplicá los gates G1–G8 entre fases. Si un gate falla, NO avances: reportá y pedí decisión.
4. Escritura atómica en `state/` (`*.tmp` + rename). Hashes SHA-256 en `state/execution-state.json`.
5. Nunca edites `pom.xml` ni `build.gradle`. Nunca `mvn clean`/`install`.
6. Cobertura solo derivada de los JaCoCo XML reales (baseline + final).
7. Antes de proponer un test, pasalo por `tools/python/test_linter.py`. Si tiene violaciones G1/G6, descartarlo sin invocar `javac`.
8. Respetar `state/generated-code-index.json#excludedFqcns` y `excludedPackages`: esas clases no son SUT.
9. Respetar `state/archetype-profile.json#implies` para `javax`/`jakarta`, JUnit y JaCoCo.

## Procedimiento
Ejecutá las fases en orden: discovery → stack-profile → classification →
symbol-contract → dependency-graph → fixtures → planning → generation →
validation → repair → reporting.

Para CADA fase:
- Listá las precondiciones que verificás (referenciando schemas).
- Mostrá los comandos exactos que ejecutarías y su salida resumida.
- Persistí el estado correspondiente y validá contra su JSON Schema.
- Esperá mi confirmación antes de saltar a la fase siguiente la primera vez;
  desde el segundo ciclo, avanzá automático salvo que falle un gate.

## Salida por fase
- Resumen de evidencia recolectada.
- Estados creados/actualizados (con path y hash).
- Gates evaluados (PASS/FAIL).
- Próxima fase.

## Salida final
Reporte de `reporting-agent` con:
- cobertura before/after por clase (derivada de XML),
- lista de tests generados con sus `evidence-ids`,
- tests descartados con `reason` (G1_*, G2_*, TQG_*, etc.),
- fixes aplicados (failure-memory),
- regresiones (si las hubo),
- riesgos y siguientes pasos.

Empezá ahora por **Phase 0 (Python pre-stage)**: verificá los `state/*.json` o ejecutá `run_pipeline.py`. Luego avanzá a **Phase 1 (Discovery)**.