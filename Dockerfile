# Servidor FastMCP de la POC (herramientas + formulario + SQLite)
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OT_DB_PATH=/app/data/ordenes.db
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py db.py catalogo.py ./
COPY scripts ./scripts
EXPOSE 8000 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import socket; socket.create_connection(('localhost', 8000), 3)" || exit 1
# MCP por HTTP en http://localhost:8000/mcp
CMD ["python", "server.py"]
