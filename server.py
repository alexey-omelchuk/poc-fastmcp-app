"""POC FastMCP Apps – Órdenes de trabajo para el agente de mantenimiento de VEKAI.

Flujo:
  1. El agente (LLM) entiende la avería y llama a `abrir_formulario_ot` con lo que ha extraído.
  2. Se muestra el formulario «Nueva orden de trabajo» precargado y editable.
  3. «Crear orden» → `CallTool(crear_ot)` → validación en servidor + alta idempotente en SQLite.

Arranque en local:
  fastmcp dev apps server.py:mcp
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastmcp import FastMCP, FastMCPApp
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult
from prefab_ui.actions import SetState, ShowToast
from prefab_ui.actions.mcp import CallTool
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Alert,
    AlertDescription,
    AlertTitle,
    Badge,
    Button,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    Column,
    Form,
    If,
    Label,
    Muted,
    Row,
    Select,
    SelectOption,
    Textarea,
)
from prefab_ui.rx import ERROR, RESULT, Rx
from pydantic import Field

import db
from catalogo import ACTIVOS, ESTADO_INICIAL, PRIORIDAD_POR_DEFECTO, PRIORIDADES, etiqueta, normalizar_activo

Prioridad = Literal["Baja", "Normal", "Alta"]

app = FastMCPApp("OrdenesTrabajo")


# ─────────────────────────────────────────────────────────────────────────────
# Backend: solo lo llama el formulario (visibility=["app"] por defecto)
# ─────────────────────────────────────────────────────────────────────────────
@app.tool()
def crear_ot(
    solicitud_id: str,
    activo: str = "",
    descripcion: str = "",
    prioridad: str = PRIORIDAD_POR_DEFECTO,
    observaciones: str = "",
) -> dict:
    """Valida y registra una orden de trabajo. Idempotente por `solicitud_id`."""
    errores: list[str] = []
    codigo = (activo or "").strip().upper()
    if not codigo:
        errores.append("Activo: selecciona un equipo de la lista.")
    elif codigo not in ACTIVOS:
        errores.append(f"Activo: «{activo}» no existe en el catálogo.")
    desc = (descripcion or "").strip()
    if not desc:
        errores.append("Descripción de la avería: es obligatoria.")
    if prioridad not in PRIORIDADES:
        errores.append(f"Prioridad: debe ser {', '.join(PRIORIDADES)}.")
    if not solicitud_id:
        errores.append("Solicitud: falta el identificador del formulario.")
    if errores:
        # El formulario muestra este mensaje y conserva lo que el usuario ya ha escrito.
        raise ToolError("Revisa estos campos → " + " | ".join(errores))

    orden, creada_ahora = db.crear_orden_idempotente(
        solicitud_id=solicitud_id,
        activo=codigo,
        descripcion=desc,
        prioridad=prioridad,
        observaciones=(observaciones or "").strip(),
        estado=ESTADO_INICIAL,
    )
    mensaje = f"Orden {orden['id']} creada · Estado: {orden['estado']}"
    if not creada_ahora:
        mensaje += " (reenvío detectado: es la misma orden, no se ha duplicado)"
    return {
        "id": orden["id"],
        "estado": orden["estado"],
        "mensaje": mensaje,
        "creada_ahora": creada_ahora,
        "altas": db.contar_altas(solicitud_id),
    }


@app.tool(model=True)
def listar_ot(limite: int = 10) -> list[dict]:
    """Lista las últimas órdenes de trabajo guardadas en la base de datos de demo."""
    return db.listar_ordenes(limite)


# ─────────────────────────────────────────────────────────────────────────────
# Entrada: la llama el agente (visible para el modelo) y abre el formulario
# ─────────────────────────────────────────────────────────────────────────────
@app.ui(title="Nueva orden de trabajo")
def abrir_formulario_ot(
    activo: Annotated[str | None, Field(description="Código del equipo si el usuario lo menciona (P-101, C-201, M-301, V-401). Si no, omitir.")] = None,
    descripcion: Annotated[str | None, Field(description="Resumen breve de la avería, p. ej. «Pérdida de agua por el cierre mecánico».")] = None,
    prioridad: Annotated[Prioridad | None, Field(description="Alta si es urgente, Baja si no corre prisa. Si no se indica, omitir (se usa Normal).")] = None,
    observaciones: Annotated[str | None, Field(description="Detalles adicionales opcionales.")] = None,
) -> ToolResult:
    """Abre el formulario «Nueva orden de trabajo» para registrar una avería de mantenimiento.

    Úsala cuando el usuario describa una avería o pida crear una orden de trabajo. Pasa lo que
    hayas entendido del mensaje:
    - activo: código del equipo si se menciona (p. ej. "P-101"). Si no se menciona, no lo pases.
    - descripcion: resumen breve de la avería (p. ej. "Pérdida de agua por el cierre mecánico").
    - prioridad: "Alta" si es urgente/crítico, "Baja" si no corre prisa; si no se indica, no la pases.
    - observaciones: cualquier detalle adicional.
    Activos disponibles: P-101, C-201, M-301, V-401.
    El usuario revisará y confirmará los datos en el formulario; no se guarda nada hasta que pulse «Crear orden».
    """
    codigo = normalizar_activo(activo)
    solicitud_id = f"SOL-{uuid.uuid4().hex[:12]}"  # un id por formulario → idempotencia
    estado_inicial = {
        "solicitud_id": solicitud_id,
        "activo": codigo or "",
        "descripcion": (descripcion or "").strip(),
        "prioridad": prioridad if prioridad in PRIORIDADES else PRIORIDAD_POR_DEFECTO,
        "observaciones": (observaciones or "").strip(),
        "altas": db.contar_altas(solicitud_id),  # siempre 0 al abrir: abrir no guarda nada
        "guardando": False,
        "resultado": None,
        "error": None,
    }
    activo_no_reconocido = bool(activo) and codigo is None

    with Card(css_class="max-w-2xl") as view:
        with CardHeader():
            with Row(gap=2, align="center"):
                CardTitle("Nueva orden de trabajo")
                Badge("Demo", variant="secondary")
            CardDescription("Revisa los datos que ha entendido el agente, corrige lo que haga falta y pulsa «Crear orden».")
        with CardContent():
            with Column(gap=4):
                with Form(
                    on_submit=[
                        SetState("guardando", True),
                        SetState("error", None),
                        CallTool(
                            crear_ot,
                            arguments={
                                "solicitud_id": solicitud_id,
                                "activo": Rx("activo"),
                                "descripcion": Rx("descripcion"),
                                "prioridad": Rx("prioridad"),
                                "observaciones": Rx("observaciones"),
                            },
                            on_success=[
                                SetState("guardando", False),
                                SetState("resultado", RESULT),
                                SetState("altas", RESULT.altas),
                                ShowToast(RESULT.mensaje, variant="success"),
                            ],
                            on_error=[
                                SetState("guardando", False),
                                SetState("error", ERROR),
                            ],
                        ),
                    ]
                ):
                    # Activo (obligatorio)
                    with Column(gap=1):
                        with Row(gap=2, align="center"):
                            Label("Activo *")
                            with If(~Rx("activo")):
                                Badge("Pendiente: elige un equipo", variant="destructive")
                        if activo_no_reconocido:
                            Muted(f"El agente indicó «{activo}», que no está en el catálogo de prueba.")
                        with Select(name="activo", placeholder="Selecciona un activo…"):
                            for cod in ACTIVOS:
                                SelectOption(value=cod, label=etiqueta(cod))

                    # Descripción (obligatoria)
                    with Column(gap=1):
                        Label("Descripción de la avería *")
                        Textarea(name="descripcion", placeholder="¿Qué le pasa al equipo?", rows=3)

                    # Prioridad (Normal por defecto)
                    with Column(gap=1):
                        Label("Prioridad")
                        with Select(name="prioridad"):
                            for p in PRIORIDADES:
                                SelectOption(value=p, label=p)

                    # Observaciones (opcional)
                    with Column(gap=1):
                        Label("Observaciones")
                        Textarea(name="observaciones", placeholder="Opcional", rows=2)

                    Button(
                        Rx("guardando").then("Creando…", "Crear orden"),
                        button_type="submit",
                        disabled=Rx("guardando"),
                    )

                with If(Rx("error")):
                    with Alert(variant="destructive"):
                        AlertTitle("No se ha podido crear la orden")
                        AlertDescription(Rx("error"))

                with If(Rx("resultado")):
                    with Alert(variant="success"):
                        AlertTitle(Rx("resultado").mensaje)
                        AlertDescription(f"Puedes cerrar el formulario. Solicitud {solicitud_id}.")

                Muted(f"Solicitud {solicitud_id} · Altas registradas para esta solicitud: {{{{ altas }}}}")

    resumen = (
        f"Formulario de OT abierto (solicitud {solicitud_id}). "
        f"Activo: {codigo or 'PENDIENTE'}; descripción: {estado_inicial['descripcion'] or 'vacía'}; "
        f"prioridad: {estado_inicial['prioridad']}. Aún no se ha guardado nada: el usuario debe revisar y pulsar «Crear orden»."
    )
    return ToolResult(content=resumen, structured_content=PrefabApp(view=view, state=estado_inicial))


mcp = FastMCP("VEKAI Mantenimiento – POC OT", providers=[app])

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
