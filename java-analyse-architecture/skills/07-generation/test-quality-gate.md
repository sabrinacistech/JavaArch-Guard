# Test Quality Gate

## Objetivo
Rechazar tests de baja señal antes de gastar build/coverage.

## Reglas (cada una bloquea el test)
1. Debe contener al menos un assert real o `verify(...)` con interacción del SUT.
2. Prohibido `assertTrue(true)`, `assertNotNull(obj)` como único assert.
3. Prohibido `Thread.sleep`, `Awaitility` sin timeout, `System.currentTimeMillis()`, `Math.random()`.
4. Prohibido dependencia entre tests (`@TestMethodOrder` solo si justificado y registrado).
5. Prohibido stubs irrelevantes (`when(mock.x()).thenReturn(...)` sin que el SUT invoque `x`). Verificar contra `dependency-graph.json`.
6. Prohibido `verifyNoMoreInteractions` salvo en escenarios negativos explícitos.
7. Cada `try/catch` debe terminar en `fail()` o assert sobre la excepción; nunca silenciar.
8. Cobertura accidental: si el test no toca el método objetivo (verificado por JaCoCo del batch), descartar.

## Salida
Tests rechazados van a `discardedTests[]` del ciclo con `reason: TQG_<código>` y nunca se compilan.
