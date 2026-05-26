# Classification Agent

> **Phase 7 — Consolidación**: este agente sigue disponible para compat. Las nuevas
> pipelines deben usar `agents/repository-intelligence-agent.md`.

> **Phase 1 — Semantic Index**: la clasificación se deriva determinísticamente de
> `state/index/annotations.json` + `state/index/dependencies.json`. El LLM **no**
> detecta frameworks por patrones textuales; consume el índice y, a lo sumo,
> arbitra entre etiquetas ambiguas con evidencia citada.
>
> Ver: `skills/00-runtime/semantic-index.md` y `skills/00-runtime/deterministic-analysis-policy.md`.


## Responsabilidad
Asignar tipo, etiquetas, riesgo y score por clase productiva. Excluye código generado y configs sin lógica.

## Skills
- `skills/02-classification/testability-classifier.md`
- `skills/02-classification/framework-risk-classifier.md`
- `skills/02-classification/freebuilder-classifier.md`
- `skills/02-classification/generated-code-policy.md`

## Entradas
- `state/discovery-summary.json`
- `state/stack-profile.json`
- (Opcional) `target/site/jacoco/jacoco.xml` para `coverage` actual.

## Salida
- `state/classification-index.json` (valida `_schemas/classification-index.schema.json`).

## Reglas
- Score ≥ 0 y ≤ 100.
- Toda clase generada o `@Generated` ⇒ `type: generated`, excluida de targets.
- Etiquetas (`tags`) determinan estrategia downstream (slices Spring, FreeBuilder, etc.).
