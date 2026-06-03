"""Golden-Standard Microservice Guard (GSMG).

Sistema hibrido determinista/LLM para verificar el cumplimiento del
"Golden Standard" de microservicios (Resiliencia, Observabilidad,
Independencia de datos, Clean Code).

Arquitectura:
- Capa de extraccion determinista (0 tokens): parsers AST sobre Java/configs.
- Estado global tipado: contexto inmutable que comparten los nodos.
- Orquestador Supervisor: enrutamiento hibrido (reglas duras + LLM-router).
- Skills especializados: un agente por pilar, fan-out paralelo.
"""
__version__ = "0.3.0"
