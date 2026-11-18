# POC FastMCP Apps · Órdenes de trabajo (agente de mantenimiento VEKAI)

Prueba de concepto: el usuario describe una avería en el chat, el agente abre el formulario
**Nueva orden de trabajo** con lo que ha entendido, el usuario lo revisa y pulsa **Crear orden**,
y la OT se guarda en **SQLite**.

![Demo](docs/demo.gif)

> Datos de demo: catálogo de equipos **ficticio** (P-101, C-201, M-301, V-401). No se conecta a ningún sistema real.
> Vídeo completo (2 min): [`docs/demo.mp4`](docs/demo.mp4).

## Arranque rápido (Docker, en WSL)

```bash
docker compose up -d                    # chat Chainlit → http://localhost:8001  (+ servidor MCP en :8000)
docker compose --profile visor up -d    # además, visor de FastMCP → http://localhost:8080
docker compose logs visor               # URL de arranque del visor
docker compose exec mcp python scripts/ver_db.py   # filas guardadas en SQLite
docker compose --profile visor down     # parar todo
```

La **API key de Groq** (LLM del chat) se lee de `../var_entorno_groq.txt` (`GROQ_API_KEY=...`), es
decir, de la carpeta padre del proyecto, o de un `.env` en la raíz. Nunca se sube al repo. Si el
modelo por defecto no está disponible, añade `GROQ_MODEL=<modelo>` al `.env`.

## Qué tiene que salir (flujo del correo)

| # | Haces | Ves |
|---|---|---|
| 1 | En el chat, botón **«OT precargada (P-101)»** o escribes *«Crea una orden para la bomba P-101. Pierde agua por el cierre mecánico y es urgente»* | Formulario con **P-101**, **«Pérdida de agua por el cierre mecánico»** y prioridad **Alta**, todo editable. Debajo: *Altas registradas para esta solicitud: 0* |
| 2 | **Crear orden** | **«Orden OT-DEMO-0001 creada · Estado: Abierta»** |
| 3 | **Crear orden** otra vez (doble clic o reintento) | La misma OT (*reenvío detectado*). Sigue habiendo **una sola fila** |
| 4 | *«El motor de la cinta hace un ruido metálico al arrancar»* | El activo sale **Pendiente** con un selector de los 4 equipos |
| 5 | **Crear orden** sin elegir activo | Error *«Revisa estos campos → Activo…»*. Lo escrito **se conserva** |
| 6 | Eliges **M-301** → **Crear orden** | **«Orden OT-DEMO-0002 creada · Estado: Abierta»** |
| 7 | `docker compose exec mcp python scripts/ver_db.py` (o pregúntale al agente *«¿Qué órdenes hay guardadas?»*) | Las filas en SQLite, con estado **Abierta** |

**En el visor de FastMCP** (http://localhost:8080 o `fastmcp dev apps server.py:mcp`): elige
`abrir_formulario_ot`, rellena los argumentos (lo que haría el agente) y pulsa *Launch*. Sale el
mismo formulario.

## Cómo está hecho

```
Chainlit (chat, :8001) ──MCP/HTTP──► Servidor FastMCP (:8000) ──► SQLite (data/ordenes.db)
  agente = LLM de Groq                 abrir_formulario_ot  (@app.ui, la llama el agente)
  McpApp.jsx pinta el formulario       crear_ot             (@app.tool, la llama el formulario con CallTool)
```

| Archivo | Qué hace |
|---|---|
| `server.py` | `FastMCPApp`: **`abrir_formulario_ot`** devuelve el formulario Prefab precargado; **`crear_ot`** valida, genera `OT-DEMO-000N` con estado **Abierta** y guarda |
| `db.py` | SQLite. Alta **idempotente**: cada formulario tiene un `solicitud_id` único (`UNIQUE`), y un reenvío devuelve la misma OT |
| `catalogo.py` | Equipos ficticios, prioridades (Baja / **Normal** por defecto / Alta) y estado inicial |
| `chat/app.py` | Chat **Chainlit** con agente **Groq**: le pasa las herramientas MCP (sin `crear_ot`) y pinta el formulario |
| `chat/public/elements/McpApp.jsx` | Chainlit no pinta MCP Apps de serie: este componente lo hace (iframe aislado + puente de mensajes) |
| `scripts/ver_db.py` | Ver filas guardadas (`python scripts/ver_db.py`) o altas de una solicitud (`… SOL-xxxx`) |
| `tests/test_ot.py` | Pruebas de cada punto del correo (`pytest -q`) |
| `docs/` | [Plan](docs/PLAN.md) · [Guion de la reunión](docs/PRESENTACION.md) · [Estado en VEKAI](docs/VEKAI.md) · vídeo |

**Reglas importantes:**
- La IA **no puede guardar**. `crear_ot` es solo visible para el formulario; quien confirma es el usuario.
- La validación se hace **en el servidor**: el activo existe, la descripción tiene contenido y la prioridad es válida.
- Abrir el formulario **no escribe nada** en la base de datos.

## Sin Docker (Python 3.11 o superior)

El servidor y el chat van en **entornos separados**: Chainlit necesita `mcp<2` y FastMCP 4.2 usa `mcp 2.x`.

```bash
# Terminal 1 – servidor
python -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt
fastmcp dev apps server.py:mcp          # visor (lo que pide el correo)   — o —   python server.py  (MCP en :8000)
pytest -q                               # pruebas

# Terminal 2 – chat
cd chat && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
chainlit run app.py --port 8001         # necesita el servidor en :8000 (python server.py)
```

## Estado en VEKAI

No se ha podido probar en el chat de VEKAI (no hay acceso). La demo queda funcionando en el
**visor de FastMCP** y en un chat **Chainlit** que hace de host igual que VEKAI. En
[docs/VEKAI.md](docs/VEKAI.md) está qué necesita VEKAI para **mostrar el formulario** y para
**guardar desde él**, con un checklist para comprobarlo.
