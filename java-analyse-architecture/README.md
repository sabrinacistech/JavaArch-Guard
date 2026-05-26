# Java Architecture Review & Compliance Agent

Arquitectura de agentes y skills para **auditar, validar y verificar el cumplimiento de arquitectura** en microservicios Java. Soporta Java 8+, Maven/Gradle, e identifica desvíos en el uso de frameworks (Spring/Jakarta), dependencias prohibidas, acoplamiento cíclico y estructuras de paquetes sin inventar símbolos ni falsos positivos.

## Principio central

> El agente no asume ni alucina reglas de negocio o estructuras. Solo puede reportar desvíos basados en AST, bytecode (`javap`) y grafos de dependencias reales verificados con un `evidence-id`. Si no hay evidencia física en los artefactos del proyecto, el desvío no se genera.

## Flujo del Agente

```text
discovery → stack-profile → dependency-graph → rule-mapping
          → static-analysis → structural-check → compliance-scoring
          → auto-repair-proposals → reporting