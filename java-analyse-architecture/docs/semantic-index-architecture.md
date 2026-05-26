# Semantic Index Architecture

> Phase 1 of the optimization roadmap. See `docs/optimization-roadmap.md`.

## Motivación

El sistema original realiza análisis estructural de forma redundante:

- `discovery-agent` lee POMs y estructura de carpetas.
- `classification-agent` re-lee `.java` para detectar Spring/JPA/etc.
- `dependency-graph-agent` reconstruye dependencias por su cuenta.
- `symbol-contract-agent` invoca `javap`/JavaParser de nuevo.
- `stack-profile-agent` repite parte del trabajo anterior.

Resultado: O(N agentes × M archivos) operaciones de parseo en lugar de O(M).

## Solución

Una capa de índice persistente y determinística (`state/index/`) producida por el
pre-stage Python y consumida por todos los agentes vía lookups O(1) sobre JSON.

```
┌──────────────────────┐
│  Python pre-stage    │  javap + JavaParser + SymbolSolver
│  tools/python/       │──┐
└──────────────────────┘  │  (escritura atómica + fingerprints SHA-256)
                          ▼
                ┌─────────────────────┐
                │  state/index/*.json │
                └────────┬────────────┘
                         │ lookups O(1)
   ┌────────┬────────────┼────────────┬────────┐
   ▼        ▼            ▼            ▼        ▼
discovery class.    dependency   symbol.    stack
agent    agent      graph agent  contract   profile
                                   agent      agent
```

## Esquemas

Cada archivo de índice valida contra un schema en `state/_schemas/index/`:

- `classes.schema.json` — `{ fqcn, file, kind, modifiers, supertypes[], interfaces[] }`
- `methods.schema.json` — `{ fqcn, name, descriptor, params[], return, modifiers, throws[] }`
- `imports.schema.json` — `{ file, imports[{ fqn, static, onDemand }] }`
- `dependencies.schema.json` — nodos `{ fqcn }` y aristas `{ from, to, kind }` con `kind ∈ {extends, implements, uses, injects, throws, returns, param}`.
- `annotations.schema.json` — `{ target, annotations[{ fqn, attrs }] }`.

## Determinismo

- **Sin LLM**. La construcción del índice es 100% determinística.
- **Precedencia**: bytecode (`javap -p -s -c`) → AST (JavaParser+SymbolSolver) → fallback a `target/generated-sources`.
- **Reproducible**: dos corridas sobre el mismo árbol de fuentes producen byte-exact los mismos JSON (orden estable por FQCN).

## Invalidación

- Granularidad: por archivo `.java` y por `pom.xml`.
- `execution-state.json.indexFingerprints[file] = sha256(file)`.
- Si `target/classes/<fqcn>.class` es más nuevo que la entrada indexada → reindex puntual.
- Cambios de schema (`version` bump) → reindex total.

## Backward compatibility

| Antes                                         | Después                                |
|-----------------------------------------------|----------------------------------------|
| Cada agente parseaba lo que necesitaba.       | Los agentes consultan `state/index/`. |
| `symbol-contract-agent` lanzaba `javap` ad-hoc.| `symbol-contract-agent` deriva de `methods.json` + `annotations.json`. |
| `dependency-graph.json` se reconstruía completo. | Vista filtrada/derivada de `dependencies.json`. |

Los archivos legacy (`symbol-contracts/`, `dependency-graph.json`, `import-whitelist.json`,
`classification-index.json`) siguen existiendo y son los que la fase de Generation
consume. El índice es la **fuente** que los alimenta.

## Riesgos y mitigaciones

| Riesgo                              | Mitigación                                              |
|-------------------------------------|---------------------------------------------------------|
| Índice desincronizado con sources   | Fingerprints + bloqueo `BLOCKED_INDEX_STALE`            |
| Crecimiento de `state/index/`       | Compresión opcional (`.json.zst`) sobre repos grandes  |
| Schemas evolucionan                 | `version` field + migración por pre-stage              |
| Doble verdad (índice vs contratos)  | Contratos se derivan del índice; nunca al revés        |

## Migración (incremental)

1. Pre-stage Python escribe `state/index/*.json` (puede coexistir con contratos legacy).
2. Agentes empiezan consultando el índice; si falta, caen a su flujo original.
3. Cuando todos los agentes usan el índice, se simplifican los agentes legacy
   (Phase 7 — consolidación).
