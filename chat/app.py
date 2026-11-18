"""Chat de demo en Chainlit con un agente real (LLM de Groq) que usa el servidor FastMCP de la POC.

Hace el papel del chat de VEKAI:
  1. El usuario describe la avería.
  2. Groq decide llamar a `abrir_formulario_ot` con los datos que ha entendido.
  3. Chainlit llama a esa herramienta por MCP y pinta su interfaz (MCP App) con el
     componente propio `public/elements/McpApp.jsx`.
  4. «Crear orden» en el formulario → el componente pide a este backend que llame a `crear_ot`.

Chainlit no pinta MCP Apps de serie: `McpApp.jsx` hace de host (iframe + puente postMessage).

Variables de entorno:
  MCP_URL        URL del servidor FastMCP (por defecto http://localhost:8000/mcp)
  GROQ_API_KEY   clave de Groq; si no está, se lee de GROQ_ENV_FILE
  GROQ_ENV_FILE  fichero con GROQ_API_KEY=... (por defecto ../../var_entorno_groq.txt)
  GROQ_MODEL     modelo de Groq (opcional; si no se indica o no existe, se elige uno disponible)

Arranque:  chainlit run app.py --port 8001
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

import chainlit as cl
from chainlit.server import app as fastapi_app
from fastapi import HTTPException
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.environ.get("MCP_URL", "http://localhost:8000/mcp")
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "").strip()  # vacío = se elige solo uno disponible en tu cuenta
# Preferencia si GROQ_MODEL no está o no existe en la cuenta (modelos con llamada a herramientas)
MODELOS_PREFERIDOS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
    "moonshotai/kimi-k2-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen/qwen3-32b",
    "llama-3.1-8b-instant",
]
_modelo_elegido: str | None = None
UI_TOOL = "abrir_formulario_ot"

SYSTEM_PROMPT = """Eres el agente de mantenimiento de VEKAI (demo). Hablas en español, de forma breve.
Cuando el usuario describa una avería o pida crear una orden de trabajo, llama SIEMPRE a la
herramienta abrir_formulario_ot con lo que hayas entendido:
- activo: solo si el usuario menciona el código del equipo (P-101, C-201, M-301, V-401). Si no, no lo pases.
- descripcion: resumen breve de la avería escrito como sustantivo (estilo parte de trabajo), sin el
  código del equipo ni la urgencia. Ejemplos: «pierde agua por el cierre mecánico» → «Pérdida de agua
  por el cierre mecánico»; «hace un ruido metálico al arrancar» → «Ruido metálico al arrancar»;
  «no enciende» → «No enciende».
- prioridad: «Alta» si dice urgente/crítico/parado, «Baja» si no corre prisa; si no lo indica, no la pases.
- observaciones: otros detalles útiles, si los hay.
No inventes datos. No digas que la orden está creada: el usuario debe revisarla y pulsar «Crear orden».
Si te preguntan por órdenes ya guardadas, usa listar_ot."""


# ─── MCP ─────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def mcp_session():
    async with streamablehttp_client(MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _visibilidad(tool) -> list[str]:
    return ((tool.meta or {}).get("ui") or {}).get("visibility", ["model"])


def _dump(result) -> dict:
    return result.model_dump(by_alias=True, exclude_none=True, mode="json")


@fastapi_app.post("/ot/tools/call")
async def llamar_herramienta_desde_la_ui(body: dict):
    """El formulario (iframe) llama aquí para ejecutar herramientas del servidor (p. ej. crear_ot).

    Solo se permiten herramientas marcadas como visibles para la app (visibility incluye "app").
    """
    nombre = body.get("name")
    permitido, resultado = False, None
    async with mcp_session() as s:
        tools = {t.name: t for t in (await s.list_tools()).tools}
        if nombre in tools and "app" in _visibilidad(tools[nombre]):
            permitido = True
            resultado = _dump(await s.call_tool(nombre, body.get("arguments") or {}))
    if not permitido:  # se lanza fuera de la sesión MCP para que llegue como 403 y no como 500
        raise HTTPException(status_code=403, detail=f"La interfaz no puede llamar a «{nombre}».")
    return resultado


# ─── Groq ────────────────────────────────────────────────────────────────────
def _cargar_api_key() -> str | None:
    if os.environ.get("GROQ_API_KEY"):
        return os.environ["GROQ_API_KEY"].strip()
    defecto = Path(__file__).resolve().parents[2] / "var_entorno_groq.txt"
    fichero = Path(os.environ.get("GROQ_ENV_FILE", defecto))
    if fichero.is_file():
        for linea in fichero.read_text(encoding="utf-8").splitlines():
            if linea.strip().startswith("GROQ_API_KEY="):
                return linea.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _elegir_modelo(api_key: str) -> str:
    """Usa GROQ_MODEL si existe en la cuenta; si no, el primero disponible de MODELOS_PREFERIDOS."""
    global _modelo_elegido
    if _modelo_elegido:
        return _modelo_elegido
    req = urllib.request.Request(
        f"{GROQ_BASE_URL}/models", headers={"Authorization": f"Bearer {api_key}", "User-Agent": "vekai-ot-poc/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            disponibles = [m["id"] for m in json.loads(r.read()).get("data", []) if m.get("active", True)]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Groq respondió {e.code} al listar modelos: {e.read().decode(errors='replace')[:300]}") from e
    candidatos = ([GROQ_MODEL] if GROQ_MODEL else []) + MODELOS_PREFERIDOS
    elegido = next((m for m in candidatos if m in disponibles), None)
    if not elegido:
        raise RuntimeError(f"Ninguno de los modelos preferidos está disponible. Modelos de tu cuenta: {', '.join(sorted(disponibles))[:500]}")
    if GROQ_MODEL and elegido != GROQ_MODEL:
        print(f"[chat] GROQ_MODEL={GROQ_MODEL} no está disponible; uso {elegido}", flush=True)
    print(f"[chat] Modelo de Groq: {elegido}", flush=True)
    _modelo_elegido = elegido
    return elegido


def _llamar_groq(api_key: str, messages: list[dict], tools: list[dict]) -> dict:
    cuerpo = json.dumps(
        {"model": _elegir_modelo(api_key), "messages": messages, "tools": tools, "tool_choice": "auto", "temperature": 0}
    ).encode()
    req = urllib.request.Request(
        f"{GROQ_BASE_URL}/chat/completions",
        data=cuerpo,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": "vekai-ot-poc/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Groq respondió {e.code}: {e.read().decode(errors='replace')[:300]}") from e


def _error_legible(e: BaseException) -> str:
    """Saca el error real de los ExceptionGroup (anyio/MCP los envuelven en «unhandled errors in a TaskGroup»)."""
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    texto = f"{type(e).__name__}: {e}"
    if "urlopen error" in texto or "URLError" in texto or "timed out" in texto:
        texto += "\n→ No se puede llegar a la API de Groq (red, proxy o VPN)."
    elif "Groq respondió 401" in texto:
        texto += "\n→ La API key de Groq no es válida (revisa var_entorno_groq.txt)."
    elif "Groq respondió" in texto:
        texto += "\n→ Error de Groq. Si habla del modelo, pon GROQ_MODEL=<modelo> en un .env (o déjalo vacío para que se elija solo)."
    elif "ConnectError" in texto or "Connection refused" in texto or "Name or service not known" in texto:
        texto += f"\n→ No se puede conectar con el servidor MCP en {MCP_URL}. ¿Está arrancado? (`docker compose ps`)"
    return texto


# ─── Chainlit ────────────────────────────────────────────────────────────────
@cl.set_starters
async def starters():
    return [
        cl.Starter(label="OT precargada (P-101)", message="Crea una orden para la bomba P-101. Pierde agua por el cierre mecánico y es urgente"),
        cl.Starter(label="OT sin equipo", message="El motor de la cinta hace un ruido metálico al arrancar"),
        cl.Starter(label="Ver órdenes guardadas", message="¿Qué órdenes hay guardadas?"),
    ]


@cl.on_chat_start
async def inicio():
    cl.user_session.set("historial", [])


async def _abrir_formulario(session: ClientSession, tool, args: dict) -> str:
    """Ejecuta la herramienta con UI y la pinta en el chat con el componente McpApp."""
    resultado = await session.call_tool(tool.name, args)
    uri = tool.meta["ui"]["resourceUri"]
    recurso = (await session.read_resource(uri)).contents[0]
    resumen = next((c.text for c in resultado.content if getattr(c, "type", "") == "text"), "")
    elemento = cl.CustomElement(
        name="McpApp",
        display="inline",
        props={"toolName": tool.name, "toolInput": args, "toolResult": _dump(resultado), "html": recurso.text},
    )
    await cl.Message(content="He preparado la orden de trabajo. Revísala y pulsa **Crear orden**:", elements=[elemento]).send()
    return resumen


@cl.on_message
async def mensaje(msg: cl.Message):
    historial: list[dict] = cl.user_session.get("historial") or []
    historial.append({"role": "user", "content": msg.content})

    api_key = _cargar_api_key()
    if not api_key:
        await cl.Message(content="⚠️ Falta la API key de Groq (GROQ_API_KEY o fichero var_entorno_groq.txt).").send()
        return

    try:
        async with mcp_session() as s:
            mcp_tools = [t for t in (await s.list_tools()).tools if "model" in _visibilidad(t)]  # crear_ot queda fuera
            tools = [{"type": "function", "function": {"name": t.name, "description": t.description or "", "parameters": t.inputSchema}} for t in mcp_tools]
            por_nombre = {t.name: t for t in mcp_tools}
            messages = [{"role": "system", "content": SYSTEM_PROMPT}, *historial]

            for _ in range(3):
                resp = await asyncio.to_thread(_llamar_groq, api_key, messages, tools)
                m = resp["choices"][0]["message"]
                llamadas = m.get("tool_calls") or []
                if not llamadas:
                    texto = m.get("content") or ""
                    historial.append({"role": "assistant", "content": texto})
                    await cl.Message(content=texto).send()
                    break
                llamada = llamadas[0]
                nombre = llamada["function"]["name"]
                args = {k: v for k, v in json.loads(llamada["function"].get("arguments") or "{}").items() if v not in (None, "")}
                if nombre == UI_TOOL:
                    async with cl.Step(name=nombre, type="tool") as paso:
                        paso.input = args
                        resumen = await _abrir_formulario(s, por_nombre[nombre], args)
                        paso.output = resumen
                    historial.append({"role": "assistant", "content": f"[{nombre}] {resumen}"})
                    break
                # Herramienta de datos (listar_ot): se ejecuta y se devuelve el resultado al modelo.
                async with cl.Step(name=nombre, type="tool") as paso:
                    paso.input = args
                    res = await s.call_tool(nombre, args)
                    salida = res.structuredContent if res.structuredContent is not None else [c.text for c in res.content if hasattr(c, "text")]
                    if isinstance(salida, dict) and list(salida) == ["result"]:
                        salida = salida["result"]  # MCP envuelve las listas en {"result": [...]}
                    paso.output = salida
                messages += [
                    {"role": "assistant", "content": m.get("content") or "", "tool_calls": [llamada]},
                    {"role": "tool", "tool_call_id": llamada["id"], "content": json.dumps(salida, ensure_ascii=False, default=str)},
                ]
    except Exception as e:  # red, clave inválida, servidor MCP caído…
        detalle = _error_legible(e)
        print(f"[chat] Error: {detalle}", flush=True)  # también en `docker compose logs chat`
        await cl.Message(content=f"⚠️ Error: {detalle}").send()
    finally:
        cl.user_session.set("historial", historial)
