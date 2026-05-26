# Method Verification

## Objetivo
Registrar todos los métodos invocables sobre un tipo (públicos, protegidos accesibles, estáticos, default de interfaz). Soporta gate **G2**.

## Procedimiento
1. `javap -p -s <FQCN>` → leer firma + descriptor. Capturar:
   - nombre, modificadores, tipo de retorno (con erasure y signature genérica si presente `Signature: ...`),
   - parámetros (tipos FQCN), `throws`.
2. Fallback AST con SymbolSolver para overloads ambiguos y métodos default.
3. Marcar métodos sintéticos / bridge como no usables (`usable: false`).
4. Para overloads, generar `evidenceId` distinto por firma.

## Salida (fragmento del contrato del SUT)

```json
{
  "methods": [
    {
      "evidenceId": "sym:com.acme.FooService#calc(java.math.BigDecimal):e7a1",
      "name": "calc",
      "modifiers": ["public"],
      "returnType": "java.math.BigDecimal",
      "params": [{ "type": "java.math.BigDecimal", "name": "amount" }],
      "throws": ["com.acme.DomainException"],
      "generics": { "typeParams": [], "signature": null },
      "usable": true,
      "source": "bytecode"
    }
  ]
}
```

## Reglas
- Prohibido invocar `setX`, `getX`, factory si no aparece en `methods[]` con `usable: true`.
- Para Mockito stubs: la firma debe matchear exactamente (tipo de retorno y params); no convertir tipos primitivos a wrappers sin evidencia de overload.
- Para `void` ⇒ usar `doNothing()` / `doThrow()`, no `when(...).thenReturn(...)`.
- Métodos `final`/`static` solo mockeables si el preset Mockito declara `MockedStatic` / `mockito-inline` (ver `stack-profile.json`).
