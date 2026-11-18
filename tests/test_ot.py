"""Pruebas del flujo de la POC (se ejecutan con: pytest -q)."""

import importlib
import json
import os

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("OT_DB_PATH", str(tmp_path / "ordenes.db"))
    import db
    importlib.reload(db)
    import server as srv
    importlib.reload(srv)
    return srv


async def _abrir(c, **args):
    r = await c.call_tool("abrir_formulario_ot", args)
    return r, r.structured_content["state"]


async def test_herramientas_y_visibilidad(server):
    async with Client(server.mcp) as c:
        tools = {t.name: t for t in await c.list_tools()}
    assert tools["abrir_formulario_ot"].meta["ui"]["visibility"] == ["model"]
    assert "resourceUri" in tools["abrir_formulario_ot"].meta["ui"]
    assert tools["crear_ot"].meta["ui"]["visibility"] == ["app"]


async def test_precarga_desde_el_chat(server):
    async with Client(server.mcp) as c:
        r, st = await _abrir(c, activo="bomba P-101", descripcion="Pérdida de agua por el cierre mecánico", prioridad="Alta")
    assert st["activo"] == "P-101"
    assert st["descripcion"] == "Pérdida de agua por el cierre mecánico"
    assert st["prioridad"] == "Alta"
    assert st["altas"] == 0
    assert "crear_ot" in json.dumps(r.structured_content)  # el envío está enlazado a crear_ot


async def test_activo_pendiente_y_prioridad_normal_por_defecto(server):
    async with Client(server.mcp) as c:
        _, st = await _abrir(c, descripcion="Ruido raro")
        _, st2 = await _abrir(c, activo="X-999")
    assert st["activo"] == "" and st["prioridad"] == "Normal"
    assert st2["activo"] == ""  # no está en el catálogo → pendiente


async def test_abrir_no_guarda_nada(server):
    import db
    async with Client(server.mcp) as c:
        _, st = await _abrir(c, activo="P-101", descripcion="Fuga")
    assert db.contar_altas(st["solicitud_id"]) == 0
    assert db.listar_ordenes() == []


async def test_validacion_en_servidor(server):
    async with Client(server.mcp) as c:
        with pytest.raises(ToolError) as e:
            await c.call_tool("crear_ot", {"solicitud_id": "S1", "activo": "Z-1", "descripcion": "  ", "prioridad": "Urgente"})
    msg = str(e.value)
    assert "Activo" in msg and "Descripción" in msg and "Prioridad" in msg


async def test_crear_y_doble_envio_una_sola_orden(server):
    import db
    async with Client(server.mcp) as c:
        _, st = await _abrir(c, activo="P-101", descripcion="Pérdida de agua por el cierre mecánico", prioridad="Alta")
        args = {k: st[k] for k in ("solicitud_id", "activo", "descripcion", "prioridad", "observaciones")}
        r1 = (await c.call_tool("crear_ot", args)).data
        r2 = (await c.call_tool("crear_ot", args)).data
    assert r1["mensaje"] == "Orden OT-DEMO-0001 creada · Estado: Abierta"
    assert r1["creada_ahora"] is True and r2["creada_ahora"] is False
    assert r1["id"] == r2["id"] == "OT-DEMO-0001"
    assert db.contar_altas(st["solicitud_id"]) == 1
    assert len(db.listar_ordenes()) == 1


async def test_numeracion_correlativa(server):
    async with Client(server.mcp) as c:
        a = (await c.call_tool("crear_ot", {"solicitud_id": "A", "activo": "C-201", "descripcion": "x"})).data
        b = (await c.call_tool("crear_ot", {"solicitud_id": "B", "activo": "V-401", "descripcion": "y", "prioridad": "Baja"})).data
    assert (a["id"], b["id"]) == ("OT-DEMO-0001", "OT-DEMO-0002")
