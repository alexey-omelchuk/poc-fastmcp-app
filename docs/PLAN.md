# Plan – POC FastMCP Apps: órdenes de trabajo (agente de mantenimiento VEKAI)

## Objetivo
Que un usuario describa una avería en el chat, el agente abra un formulario **Nueva orden de
trabajo** precargado con lo que ha entendido, el usuario lo revise/corrija y pulse **Crear orden**
para registrarla en una base de datos SQLite local con datos de demo.

## Requisitos (del correo) → cómo se cumplen

| # | Requisito | Implementación |
|---|---|---|
| 1 | `FastMCPApp` con `abrir_formulario_ot` (`@app.ui()`) que recibe los datos extraídos por el agente | `server.py` → `abrir_formulario_ot(activo, descripcion, prioridad, observaciones)` devuelve un `PrefabApp` |
| 2 | `crear_ot` con `@app.tool()` enlazada al envío con `CallTool` | `Form(on_submit=CallTool(crear_ot, arguments=…))` |
| 3 | Precarga: P-101 / «Pérdida de agua por el cierre mecánico» / Alta | El agente pasa esos argumentos; el formulario los muestra en sus campos (editables) |
| 4 | Equipo no identificado → campo pendiente + selector de activos de prueba | Si `activo` falta o no existe en el catálogo: selector vacío + aviso «Activo pendiente» |
| 5 | Validación en servidor: activo existe, descripción con contenido, prioridad válida | `crear_ot` → `ToolError` con la lista de campos a corregir |
| 6 | Genera ID y estado **Abierta** | `OT-DEMO-0001`, `OT-DEMO-0002`… y `estado='Abierta'` |
| 7 | Mensaje «Orden OT-DEMO-0001 creada · Estado: Abierta» en el formulario | `SetState("resultado", RESULT)` + `Alert` |
| 8 | Error → el usuario ve qué corregir y conserva lo escrito | `on_error` → `Alert` destructivo; los campos son estado del formulario y no se borran |
| 9 | Identificador por formulario: doble clic/reintento = misma OT | `solicitud_id` (UUID) generado al abrir; `UNIQUE` en SQLite; un reintento devuelve la OT existente |
| 10 | Al abrir el formulario: cero altas para esa solicitud | `abrir_formulario_ot` no escribe nada; el formulario muestra «Altas para esta solicitud: 0» y `scripts/ver_db.py` lo comprueba |
| 11 | Campos: Activo (obligatorio, 3-4 equipos), Descripción (obligatoria), Prioridad (Baja/Normal/Alta, Normal por defecto), Observaciones (opcional) | Ver `catalogo.py` y el formulario |
| 12 | Arrancar con `fastmcp dev apps server.py:mcp` | Documentado y probado |
| 13 | Comprobar si el chat de VEKAI puede mostrar el formulario y ejecutar el guardado | Sin acceso a VEKAI desde esta POC → documentado como punto pendiente con checklist en `docs/VEKAI.md` |
| 14 | Entregables: código, README corto, demo 2-3 min | `README.md`, `docs/demo.mp4` (grabación del chat) y guion en `docs/PRESENTACION.md` |
| 15 | Chat de prueba en **Chainlit** con LLM de **Groq** (petición del equipo) | `chat/`: Chainlit + Groq; `McpApp.jsx` hace de host de MCP Apps porque Chainlit no lo trae de serie |

## Arquitectura
```
Usuario ──► Agente (LLM del chat)
              │  extrae activo / descripción / prioridad
              ▼
        abrir_formulario_ot  (@app.ui, visible para el modelo)
              │  devuelve UI Prefab (formulario) + solicitud_id nuevo
              ▼
        Formulario en el chat (iframe sandbox, renderer Prefab)
              │  «Crear orden» → CallTool
              ▼
        crear_ot  (@app.tool, solo visible para la UI)
              │  valida + INSERT idempotente por solicitud_id
              ▼
        SQLite  data/ordenes.db  (tabla ordenes)
```

Despliegue: dos servicios separados (Chainlit necesita `mcp<2` y FastMCP 4.2 usa `mcp 2.x`):
`mcp` (servidor FastMCP, :8000) y `chat` (Chainlit, :8001), que hablan por MCP sobre HTTP, igual que lo haría VEKAI.

Archivos:
- `server.py` – `FastMCPApp`, herramientas y formulario.
- `catalogo.py` – catálogo ficticio de equipos.
- `db.py` – SQLite: esquema, alta idempotente, consultas.
- `scripts/ver_db.py` – ver filas guardadas / altas por solicitud.
- `tests/test_ot.py` – pruebas del flujo (precarga, pendiente, validación, idempotencia, cero altas).
- `chat/app.py` – agente en Chainlit (Groq + cliente MCP); `chat/public/elements/McpApp.jsx` – host MCP Apps dentro de Chainlit.

## Fuera de alcance
Autenticación, sistema real de mantenimiento (GMAO/ERP), usuarios/roles.

## Criterios de aceptación
- Las pruebas de `tests/` pasan.
- En `fastmcp dev apps` se ve el formulario precargado, el caso de activo pendiente, el error de
  validación conservando datos y el mensaje de OT creada.
- Doble envío → una sola fila en SQLite.
