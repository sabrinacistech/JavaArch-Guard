# Dependency Graph Agent

> **Phase 7 — Consolidación**: este agente sigue disponible para compat. Las nuevas
> pipelines deben usar `agents/repository-intelligence-agent.md`.

> **Phase 1 — Semantic Index**: el grafo se materializa como **vista filtrada** de
> `state/index/dependencies.json`. Este agente **no** reconstruye el grafo desde
> `.java`; agrupa, recorta por SUT y persiste `state/dependency-graph.json` para
> consumo de Generation. Si el índice falta, abortar con `BLOCKED_INDEX_MISSING`.
>
> Ver: `skills/00-runtime/semantic-index.md`.


## Responsabilidad
Mapear DI real, métodos de colaboradores efectivamente invocados, clientes externos, excepciones declaradas y, si aplica, estrategia Spring por SUT.

## Skills
- `skills/04-dependency-graph/constructor-dependency-map.md`
- `skills/04-dependency-graph/repository-method-map.md`
- `skills/04-dependency-graph/external-client-map.md`
- `skills/04-dependency-graph/spring-dependency-map.md`

## Entradas
- `state/symbol-contracts/<fqcn>.json` por cada SUT.
- `state/stack-profile.json`.

## Salida
- `state/dependency-graph.json` (valida `_schemas/dependency-graph.schema.json`).

## Reglas
- Solo registra métodos de colaboradores **efectivamente invocados** por el SUT (anti-overstub).
- Registra excepciones por método para habilitar tests negativos sin invención.
- Para Spring: declara `slice` admisible (`WebMvcTest`, `DataJpaTest`, `none`); `@SpringBootTest` queda fuera de scope.
