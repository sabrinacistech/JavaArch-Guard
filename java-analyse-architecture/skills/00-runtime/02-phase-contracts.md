# Phase Contracts

Cada fase declara entradas, salidas, precondiciones y criterio de avance. El Orchestrator bloquea avance si alguna falla.

| Fase | Entradas | Salidas | Precondición | Criterio de avance |
|------|----------|---------|--------------|---------------------|
| 1 Discovery | repo | `build-tool-contract.json`, `discovery-summary.json` | repo accesible | módulos y build tool identificados |
| 2 Stack Profile | discovery | `stack-profile.json` | discovery PASS | G5 satisfecho |
| 3 Classification | discovery, stack-profile | `classification-index.json` | G5 | clases clasificadas con score |
| 4 Symbol Contract | classification, stack-profile | `symbol-contracts/<fqcn>.json`, `import-whitelist.json` | G3, G4 satisfechos | contratos para SUTs del batch presentes |
| 5 Dependency Graph | symbol-contracts | `dependency-graph.json` | fase 4 OK | colaboradores y excepciones mapeados |
| 6 Fixtures | symbol-contracts, dep-graph | `fixture-catalog.json` | fase 5 OK | fixtures para todos los tipos requeridos del batch |
| 7 Planning | classification, JaCoCo XML, mode | `coverage-targets.json`, `batch-plan.json` | fases 4-6 OK | batch con N objetivos ordenados |
| 8 Generation | batch-plan, contratos, fixtures | tests propuestos, `generated-tests.json` | G1, G2, G5 | tests con `evidence-ids` |
| 9 Validation | tests propuestos | `compile-error-index.json`, `coverage-summary.json`, `coverage-delta.json` | G6 PASS | build narrow ejecutado |
| 10 Repair | compile-error-index | tests actualizados | matriz aplicable, G7 | error resuelto o test descartado |
| 11 Reporting | todos los estados | reporte final | ciclo cerrado | XML JaCoCo adjunto |

## Regla global
Avanzar sin precondición ⇒ FAIL del Orchestrator (no continuar).
