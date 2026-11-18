"""Catálogo ficticio de equipos para la demo (no son equipos reales)."""

ACTIVOS: dict[str, str] = {
    "P-101": "Bomba centrífuga de agua de proceso",
    "C-201": "Compresor de aire de planta",
    "M-301": "Motor de la cinta transportadora 3",
    "V-401": "Válvula de control de vapor",
}

PRIORIDADES = ("Baja", "Normal", "Alta")
PRIORIDAD_POR_DEFECTO = "Normal"
ESTADO_INICIAL = "Abierta"


def normalizar_activo(valor: str | None) -> str | None:
    """Devuelve el código del catálogo si `valor` lo identifica (p. ej. 'p101', 'bomba P-101').

    Si no se reconoce, devuelve None (el formulario lo deja pendiente).
    """
    if not valor:
        return None
    compacto = "".join(ch for ch in valor.upper() if ch.isalnum())
    for codigo in ACTIVOS:
        if codigo.replace("-", "") in compacto:
            return codigo
    return None


def etiqueta(codigo: str) -> str:
    return f"{codigo} · {ACTIVOS[codigo]}"
