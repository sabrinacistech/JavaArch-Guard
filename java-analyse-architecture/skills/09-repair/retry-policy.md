# Retry Policy

## Reglas
- Máximo **2** intentos de reparación por test propuesto.
- Máximo **1** intento por `(test, fixId)` (G7 bloquea repeticiones).
- Entre intentos: re-correr G1 + G6 antes de gastar build.
- Si el segundo intento falla ⇒ test descartado, registrado en `discardedTests[]`, y el objetivo vuelve a planning con flag `revisit: true`.
- Si `compileFailRate` del ciclo > 0.5 ⇒ abortar ciclo (G8). No seguir reparando.

## Prohibido
- Retries ciegos sin parser de errores.
- Bajar el `assert` para "hacer pasar" un test.
- Marcar `@Disabled`/`@Ignore` como reparación.
