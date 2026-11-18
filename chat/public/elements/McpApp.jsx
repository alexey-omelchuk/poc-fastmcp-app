// Componente de Chainlit que hace de "host" de MCP Apps (Chainlit no lo trae de serie).
// - Pinta el HTML de la herramienta (props.html) en un iframe aislado (sandbox).
// - Habla con el iframe por postMessage (JSON-RPC, dialecto "ui/*" de MCP Apps):
//     ui/initialize → responde con las capacidades del host
//     ui/notifications/initialized → le pasa la entrada y el resultado de la herramienta
//     tools/call → lo reenvía al backend de Chainlit (/ot/tools/call), que llama al servidor MCP
//     ui/notifications/size-changed → ajusta la altura
//     ui/message → lo escribe en el chat como si fuera el usuario
import { useEffect, useRef, useState } from "react";

export default function McpApp() {
  const ref = useRef(null);
  const [height, setHeight] = useState(560);

  useEffect(() => {
    const iframe = ref.current;
    if (!iframe) return;
    const send = (msg) => iframe.contentWindow && iframe.contentWindow.postMessage({ jsonrpc: "2.0", ...msg }, "*");

    const onMessage = async (ev) => {
      if (ev.source !== iframe.contentWindow) return;
      const m = ev.data;
      if (!m || m.jsonrpc !== "2.0" || !m.method) return;

      switch (m.method) {
        case "ui/initialize":
          send({
            id: m.id,
            result: {
              protocolVersion: (m.params && m.params.protocolVersion) || "2026-01-26",
              hostInfo: { name: "chainlit-vekai-demo", version: "1.0.0" },
              hostCapabilities: { serverTools: {}, logging: {}, message: { text: {} }, updateModelContext: { text: {} } },
              hostContext: { theme: "light", displayMode: "inline", availableDisplayModes: ["inline"] },
            },
          });
          break;
        case "ui/notifications/initialized":
          send({ method: "ui/notifications/tool-input", params: { arguments: props.toolInput || {} } });
          send({ method: "ui/notifications/tool-result", params: props.toolResult });
          break;
        case "ui/notifications/size-changed":
          if (m.params && m.params.height) setHeight(Math.min(Math.ceil(m.params.height) + 8, 1400));
          break;
        case "tools/call":
          try {
            const r = await fetch("/ot/tools/call", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(m.params || {}),
            });
            const j = await r.json();
            if (r.ok) send({ id: m.id, result: j });
            else send({ id: m.id, error: { code: -32603, message: j.detail || "Error al llamar a la herramienta" } });
          } catch (e) {
            send({ id: m.id, error: { code: -32603, message: String(e) } });
          }
          break;
        case "ui/message": {
          const texto = ((m.params && m.params.content) || []).map((c) => c.text || "").join("\n");
          if (texto) sendUserMessage(texto);
          send({ id: m.id, result: {} });
          break;
        }
        default:
          // ping, ui/update-model-context, ui/open-link… → se aceptan sin hacer nada
          if (m.id !== undefined) send({ id: m.id, result: {} });
      }
    };

    window.addEventListener("message", onMessage);
    iframe.srcdoc = props.html;
    return () => window.removeEventListener("message", onMessage);
  }, []);

  return (
    <div className="w-full rounded-lg border overflow-hidden" style={{ minWidth: 520 }}>
      <div className="text-xs text-muted-foreground px-3 py-1 border-b">🛠 {props.toolName}</div>
      <iframe
        ref={ref}
        title={props.toolName}
        sandbox="allow-scripts allow-forms"
        style={{ width: "100%", height: height, border: 0, display: "block" }}
      />
    </div>
  );
}
