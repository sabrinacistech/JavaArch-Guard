# Reporting Agent

## Responsabilidad
Emitir reporte final con evidencia citable y XML JaCoCo adjuntos. Validar consistencia interna.

## Skills
- `skills/10-reporting/final-reporting.md`
- `skills/10-reporting/progress-reporting.md`
- `skills/10-reporting/coverage-evidence-reporting.md`

## Entradas
- `state/execution-state.json`
- `state/coverage-delta.json` por ciclo
- `state/generated-tests.json`
- `state/failure-memory.json`
- `state/_summaries/cycle-*.json`
- JaCoCo XML baseline y final

## Salida
- Reporte (Markdown o JSON) con:
  - metadatos (`repo`, `commit`, `branch`, `timestamp`),
  - modo y criterio de parada,
  - tabla cobertura `before/after/delta` por clase (derivada de XML adjuntos),
  - tests generados y `evidence-ids`,
  - tests descartados y razones,
  - fixes aplicados,
  - regresiones (si las hubo),
  - riesgos y siguientes pasos.

## Reglas
- Cero cobertura auto-reportada por LLM; siempre derivada de XML.
- Si discrepancia con XML ⇒ `status: INCONSISTENT` y abortar cierre.
- Adjuntar `state/execution-state.json` final.
