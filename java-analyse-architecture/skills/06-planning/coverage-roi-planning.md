# Coverage ROI Planning

## Fórmula de ROI
`roi = expectedGain / (estimatedCost · riskPenalty)`

Donde:
- `expectedGain`: `missedLines` (modo `coverage`) o `missedBranches` (modo `branch-coverage`) o `survivorCount` (modo `mutation-hardening`).
- `estimatedCost`: `1 + dependencies + cxty/10`.
- `riskPenalty`: `1 + risk` (risk en 0..1 desde classification).

## Ordenamiento del batch
1. ROI descendente.
2. Empate ⇒ menor `cxty` primero (más rápido a converger).
3. Empate ⇒ mayor `hasContract && hasFixtures` (siempre ya filtrado, pero para estabilidad).

## Penalizaciones
- `risk.high` (reflection, async, framework slice no soportado) ⇒ deprioritizar a fin del batch.
- SUTs con fallas previas registradas en `failure-memory.json` ⇒ aplicar factor 0.5 al ROI.
