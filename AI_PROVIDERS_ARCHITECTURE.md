# Arquitectura de proveedores de IA para Jarvis

Esta nueva estructura permite que cada usuario use sus propias claves de IA, sin depender de un solo proveedor ni de secretos en el repositorio.

## Objetivo

- cada usuario guarda sus propias claves localmente
- Jarvis usa un proveedor por defecto o prioridad configurable
- si un proveedor falla por cuota, token o error, se intenta el siguiente
- la conversación y los recuerdos se guardan localmente, sin depender del proveedor
- nuevas IAs pueden agregarse sin romper el resto del proyecto

## Archivos clave

- `ai_provider_manager.py` — gestor central de proveedores
- `jarvis_ai_providers.json` — archivo local del usuario, no se sube a GitHub
- `Jarvis_main.py` — integra el gestor en la app

## Flujo recomendado

1. El usuario abre la configuración de Jarvis
2. agrega su API key para Groq, Gemini, OpenAI, Claude, etc.
3. guarda esa configuración localmente
4. Jarvis intenta el proveedor activo
5. si falla, usa el siguiente del fallback
6. si ningún proveedor responde, Jarvis informa que la IA no pudo responder

## Proveedores base soportados

- Groq
- Gemini
- OpenAI
- Anthropic / Claude
- Mistral
- DeepSeek

## Ejemplo de uso desde Python

```python
from ai_provider_manager import AIProviderManager

manager = AIProviderManager()
manager.set_provider_key("groq", "gsk_...")
manager.set_provider_key("gemini", "AIza...")

print(manager.get_enabled_providers())
print(manager.generate("Explica brevemente qué es Jarvis."))
```

## Recomendación para producción

- guardar claves en almacenamiento local cifrado si es posible
- usar un selector de proveedor por usuario
- mantener una prioridad de fallback automática
- conservar el historial local en SQLite y recuperar fragmentos relevantes con búsqueda de texto completo

## Importante

`jarvis_ai_providers.json` debe quedar en la máquina del usuario y nunca en GitHub. Ya está ignorado en `.gitignore`.
