import React, { useEffect, useState } from "react";

const api = async (path, opts = {}) => {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
};

const EMPTY_TOOL = { name: "", description: "", method: "GET", url: "https://", auth: "none", headers: [], parameters: [] };
const EMPTY_PARAM = { name: "", type: "string", description: "", required: true, location: "query" };
const EMPTY_HEADER = { name: "", value: "" };
const METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"];

export default function App() {
  const [tab, setTab] = useState("tools");
  const [tools, setTools] = useState([]);
  const [info, setInfo] = useState(null);
  const [error, setError] = useState("");

  const loadTools = () => api("/api/tools").then(setTools).catch((e) => setError(e.message));
  const loadInfo = () => api("/api/info").then(setInfo).catch(() => {});
  useEffect(() => { loadTools(); loadInfo(); }, []);

  return (
    <div className="app">
      <header className="top">
        <div className="title">PBX<span>·</span>IA</div>
        <nav className="tabs">
          {[["tools", "Herramientas"], ["chat", "Chat"], ["settings", "Configuración"]].map(([k, label]) => (
            <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{label}</button>
          ))}
        </nav>
        <div className="status">
          {info && (
            <span className="pill">
              <i className={`dot ${info.provider}`} />
              {info.provider === "openai" ? "OpenAI" : "Ollama"} · {info.model}
            </span>
          )}
        </div>
      </header>

      {error && (
        <div className="toast" onClick={() => setError("")}>{error} <span>✕</span></div>
      )}

      {tab === "tools" && <ToolsTab tools={tools} reload={loadTools} info={info} setError={setError} />}
      {tab === "chat" && <ChatTab />}
      {tab === "settings" && <SettingsTab onSaved={loadInfo} setError={setError} />}
    </div>
  );
}

/* ----------------------------- Herramientas ----------------------------- */
function ToolsTab({ tools, reload, info, setError }) {
  const [editing, setEditing] = useState(null);
  const [isNew, setIsNew] = useState(false);
  const [query, setQuery] = useState("");
  const fileRef = React.useRef(null);

  const startNew = () => { setEditing(structuredClone(EMPTY_TOOL)); setIsNew(true); };
  const startEdit = (t) => { setEditing(structuredClone(t)); setIsNew(false); };
  const duplicate = (t) => {
    const copy = structuredClone(t);
    copy.name = `${t.name}_copia`;
    setEditing(copy); setIsNew(true);
  };

  const save = async (tool, originalName) => {
    try {
      if (isNew) await api("/api/tools", { method: "POST", body: JSON.stringify(tool) });
      else await api(`/api/tools/${encodeURIComponent(originalName)}`, { method: "PUT", body: JSON.stringify(tool) });
      setEditing(null); reload();
    } catch (e) { setError(e.message); }
  };
  const remove = async (name) => {
    if (!confirm(`¿Borrar "${name}"?`)) return;
    try { await api(`/api/tools/${encodeURIComponent(name)}`, { method: "DELETE" }); reload(); }
    catch (e) { setError(e.message); }
  };

  // Exportar / importar el set completo (útil para migrar la config entre equipos).
  const exportAll = () => {
    const blob = new Blob([JSON.stringify(tools, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "tools.json";
    a.click();
    URL.revokeObjectURL(a.href);
  };
  const importAll = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      const incoming = JSON.parse(await file.text());
      if (!Array.isArray(incoming)) throw new Error("El archivo debe ser una lista de herramientas.");
      const existing = new Set(tools.map((t) => t.name));
      for (const tool of incoming) {
        if (!tool?.name) continue;
        if (existing.has(tool.name)) await api(`/api/tools/${encodeURIComponent(tool.name)}`, { method: "PUT", body: JSON.stringify(tool) });
        else await api("/api/tools", { method: "POST", body: JSON.stringify(tool) });
      }
      reload();
    } catch (err) { setError(`Importación: ${err.message}`); }
  };

  const shown = tools.filter((t) =>
    !query || t.name.toLowerCase().includes(query.toLowerCase()) || (t.description || "").toLowerCase().includes(query.toLowerCase())
  );

  return (
    <main className="layout">
      <section className="panel">
        <div className="panel-head">
          <h2>Herramientas <span className="count">{tools.length}</span></h2>
          <div className="head-actions">
            <button className="btn ghost sm" title="Exportar a tools.json" onClick={exportAll} disabled={!tools.length}>Exportar</button>
            <button className="btn ghost sm" title="Importar desde un tools.json" onClick={() => fileRef.current?.click()}>Importar</button>
            <input ref={fileRef} type="file" accept="application/json,.json" hidden onChange={importAll} />
            <button className="btn primary sm" onClick={startNew}>+ Nueva</button>
          </div>
        </div>
        <p className={`srcpill ${info?.tools_base_url_set ? "ok" : ""}`}>
          {info?.tools_base_url_set
            ? <>API real: <code>{info.tools_base_url}</code></>
            : <>Sin <code>TOOLS_BASE_URL</code> · las pruebas devuelven datos <b>simulados</b></>}
        </p>
        {tools.length > 4 && (
          <input className="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar herramienta…" />
        )}
        <div className="cards">
          {tools.length === 0 && <p className="muted">Aún no hay herramientas. Crea una o importa un <code>tools.json</code>.</p>}
          {shown.map((t) => (
            <div
              key={t.name}
              className={`toolrow ${editing && !isNew && editing.name === t.name ? "sel" : ""}`}
              onClick={() => startEdit(t)}
            >
              <span className={`tag ${t.method}`}>{t.method}</span>
              <span className="trow-main">
                <b>{t.name}</b>
                <small>{t.description || t.url}</small>
              </span>
              <span className="row-ops">
                <button className="iconbtn" title="Duplicar" onClick={(e) => { e.stopPropagation(); duplicate(t); }}>⧉</button>
                <button className="iconbtn del" title="Borrar" onClick={(e) => { e.stopPropagation(); remove(t.name); }}>✕</button>
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        {editing ? (
          <ToolEditor tool={editing} isNew={isNew} info={info} onCancel={() => setEditing(null)} onSave={save} setError={setError} />
        ) : (
          <div className="placeholder">
            <p>Elige una herramienta o crea una nueva.</p>
            <p className="muted">
              Usa <code>{"{base}"}</code> para la URL base (<code>TOOLS_BASE_URL</code>) y <code>{"{nombre}"}</code> para
              insertar un parámetro de tipo <i>path</i> en la ruta.
            </p>
          </div>
        )}
      </section>
    </main>
  );
}

function ToolEditor({ tool, isNew, info, onCancel, onSave, setError }) {
  const [t, setT] = useState(tool);
  const [testArgs, setTestArgs] = useState({});
  const [testResult, setTestResult] = useState(null);
  const [testing, setTesting] = useState(false);
  const originalName = tool.name;

  useEffect(() => { setT(tool); setTestArgs({}); setTestResult(null); }, [tool]);

  const set = (k, v) => setT((x) => ({ ...x, [k]: v }));
  const setParam = (i, k, v) => setT((x) => ({ ...x, parameters: x.parameters.map((p, idx) => idx === i ? { ...p, [k]: v } : p) }));
  const addParam = () => setT((x) => ({ ...x, parameters: [...x.parameters, { ...EMPTY_PARAM }] }));
  const delParam = (i) => setT((x) => ({ ...x, parameters: x.parameters.filter((_, idx) => idx !== i) }));
  const headers = t.headers || [];
  const setHeader = (i, k, v) => setT((x) => ({ ...x, headers: (x.headers || []).map((h, idx) => idx === i ? { ...h, [k]: v } : h) }));
  const addHeader = () => setT((x) => ({ ...x, headers: [...(x.headers || []), { ...EMPTY_HEADER }] }));
  const delHeader = (i) => setT((x) => ({ ...x, headers: (x.headers || []).filter((_, idx) => idx !== i) }));

  // --- Vista previa de la petición real que se enviará ---
  const preview = buildPreview(t, testArgs, info);

  // --- Avisos de consistencia (no bloquean, solo guían) ---
  const warnings = [];
  const pathParams = [...t.url.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).filter((n) => n !== "base");
  for (const pn of pathParams) {
    if (!t.parameters.some((p) => p.name === pn)) warnings.push(`La URL usa {${pn}} pero no existe un parámetro con ese nombre.`);
  }
  for (const p of t.parameters) {
    if (p.location === "path" && !t.url.includes(`{${p.name}}`)) warnings.push(`El parámetro «${p.name}» es de tipo path pero no aparece en la URL como {${p.name}}.`);
  }
  if (!t.url.startsWith("http") && !t.url.includes("{base}")) warnings.push("La URL no empieza por http ni usa {base}: puede no resolverse.");

  const persist = async () => {
    try { await api("/api/tools", { method: "POST", body: JSON.stringify(t) }); }
    catch { await api(`/api/tools/${encodeURIComponent(t.name)}`, { method: "PUT", body: JSON.stringify(t) }); }
  };
  const runTest = async () => {
    setTesting(true); setTestResult(null);
    try {
      await persist();
      const r = await api(`/api/tools/${encodeURIComponent(t.name)}/test`, { method: "POST", body: JSON.stringify({ args: testArgs }) });
      setTestResult(r.result);
    } catch (e) { setError(e.message); } finally { setTesting(false); }
  };

  const estado = testResult?.estado;
  const resultKind = estado === "ERROR" ? "err" : estado === "SIMULADO" ? "sim" : testResult ? "ok" : "";

  return (
    <div className="form">
      <h2>{isNew ? "Nueva herramienta" : originalName}</h2>

      <div className="field">
        <label>Nombre</label>
        <input value={t.name} onChange={(e) => set("name", e.target.value.replace(/\s/g, "_"))} placeholder="consultar_factura" />
      </div>
      <div className="field">
        <label>Descripción <small>— el modelo la usa para decidir cuándo llamarla</small></label>
        <textarea rows={2} value={t.description} onChange={(e) => set("description", e.target.value)} placeholder="Consulta el estado de una factura por su número." />
      </div>
      <div className="grid3">
        <div className="field">
          <label>Método</label>
          <select value={t.method} onChange={(e) => set("method", e.target.value)}>{METHODS.map((m) => <option key={m}>{m}</option>)}</select>
        </div>
        <div className="field span2">
          <label>URL</label>
          <input value={t.url} onChange={(e) => set("url", e.target.value)} placeholder="https://api.ejemplo.com/v1/facturas/{numero}" />
        </div>
      </div>
      <p className="muted small url-note">
        Servicio externo: pega la URL completa (<code>https://…</code>). Usa <code>{"{base}"}</code> solo si configuraste <code>TOOLS_BASE_URL</code>.
        Para un servicio del propio equipo usa <code>host.docker.internal</code>, no <code>localhost</code>.
      </p>
      <div className="field">
        <label>Autenticación</label>
        <select value={t.auth} onChange={(e) => set("auth", e.target.value)}>
          <option value="none">Ninguna</option>
          <option value="bearer">Bearer (usa TOOLS_API_KEY global)</option>
        </select>
      </div>

      <div className="subhead">
        <label>Cabeceras <small>— para la API key del servicio externo, etc.</small></label>
        <button className="btn ghost" onClick={addHeader}>+ cabecera</button>
      </div>
      {headers.length === 0 && <p className="muted small">Sin cabeceras.</p>}
      {headers.map((h, i) => (
        <div className="hrow" key={i}>
          <input value={h.name} onChange={(e) => setHeader(i, "name", e.target.value)} placeholder="X-API-Key" />
          <input value={h.value} onChange={(e) => setHeader(i, "value", e.target.value)} placeholder="valor / token" />
          <button className="del2" onClick={() => delHeader(i)}>✕</button>
        </div>
      ))}

      <div className="subhead">
        <label>Parámetros</label>
        <button className="btn ghost" onClick={addParam}>+ parámetro</button>
      </div>
      {t.parameters.length === 0 && <p className="muted small">Sin parámetros.</p>}
      {t.parameters.map((p, i) => (
        <div className="prow" key={i}>
          <input className="pn" value={p.name} onChange={(e) => setParam(i, "name", e.target.value.replace(/\s/g, "_"))} placeholder="nombre" />
          <select value={p.type} onChange={(e) => setParam(i, "type", e.target.value)}>{["string", "number", "integer", "boolean"].map((x) => <option key={x}>{x}</option>)}</select>
          <select value={p.location} onChange={(e) => setParam(i, "location", e.target.value)}>{["path", "query", "body"].map((x) => <option key={x}>{x}</option>)}</select>
          <input className="pd" value={p.description} onChange={(e) => setParam(i, "description", e.target.value)} placeholder="descripción" />
          <label className="chk"><input type="checkbox" checked={p.required} onChange={(e) => setParam(i, "required", e.target.checked)} />req</label>
          <button className="del2" onClick={() => delParam(i)}>✕</button>
        </div>
      ))}

      {warnings.length > 0 && (
        <ul className="warnlist">{warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
      )}

      <div className="actions">
        <button className="btn primary" onClick={() => onSave(t, originalName)} disabled={!t.name}>Guardar</button>
        <button className="btn ghost" onClick={onCancel}>Cancelar</button>
      </div>

      <div className="test">
        <div className="subhead"><label>Probar</label></div>
        {t.parameters.map((p) => (
          <div className="field" key={p.name}>
            <label>{p.name} <small>{p.location}{p.required ? " · req" : ""}</small></label>
            <input value={testArgs[p.name] ?? ""} onChange={(e) => setTestArgs({ ...testArgs, [p.name]: e.target.value })} placeholder={p.description} />
          </div>
        ))}

        {/* Vista previa de la petición resultante */}
        <div className="preview">
          <div className="preview-line"><span className={`tag ${t.method}`}>{t.method}</span> <code>{preview.url}</code></div>
          {preview.auth && <div className="preview-sub">Authorization: {preview.auth}</div>}
          {preview.headers.map((h, i) => <div className="preview-sub" key={i}>{h}</div>)}
          {preview.body && <div className="preview-sub">body: <code>{preview.body}</code></div>}
        </div>

        <button className="btn" onClick={runTest} disabled={testing || !t.name}>{testing ? "Ejecutando…" : "Ejecutar"}</button>
        {testResult && (
          <div className={`result-box ${resultKind}`}>
            <div className="result-head">
              <span className="badge">{estado === "ERROR" ? "✕ Error" : estado === "SIMULADO" ? "◐ Simulado" : "✓ Respuesta"}</span>
              <button className="btn ghost sm" onClick={() => navigator.clipboard?.writeText(JSON.stringify(testResult, null, 2))}>Copiar</button>
            </div>
            <pre className="result">{JSON.stringify(testResult, null, 2)}</pre>
          </div>
        )}
      </div>
    </div>
  );
}

// Construye una vista previa legible de la petición HTTP resultante.
function buildPreview(t, testArgs, info) {
  const base = info?.tools_base_url || "{base}";
  let url = (t.url || "").replace("{base}", base);
  const query = [];
  const body = {};
  for (const p of t.parameters || []) {
    const v = testArgs[p.name];
    if (p.location === "path") {
      url = url.replace(`{${p.name}}`, v != null && v !== "" ? encodeURIComponent(v) : `:${p.name}`);
    } else if (p.location === "body") {
      if (v != null && v !== "") body[p.name] = v;
    } else if (v != null && v !== "") {
      query.push(`${encodeURIComponent(p.name)}=${encodeURIComponent(v)}`);
    }
  }
  if (query.length) url += (url.includes("?") ? "&" : "?") + query.join("&");
  const hdrs = (t.headers || [])
    .filter((h) => h.name)
    .map((h) => `${h.name}: ${h.value ? (/key|token|secret|auth/i.test(h.name) ? "••••••" : h.value) : "(vacío)"}`);
  return {
    url,
    auth: t.auth === "bearer" ? (info?.api_key_set ? "Bearer ••••••" : "Bearer <falta TOOLS_API_KEY>") : "",
    headers: hdrs,
    body: Object.keys(body).length ? JSON.stringify(body) : "",
  };
}

/* --------------------------------- Chat --------------------------------- */
function ChatTab() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

  const send = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    const next = [...messages, { role: "user", content: text }];
    setMessages(next); setSending(true);
    try {
      const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: text, history }) });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "error");
      setMessages([...next, { role: "assistant", content: data.reply, tool_calls: data.tool_calls }]);
    } catch (e) {
      setMessages([...next, { role: "assistant", content: "⚠️ " + e.message }]);
    } finally { setSending(false); }
  };

  return (
    <main className="panel chat">
      <div className="messages">
        {messages.length === 0 && <p className="muted center">Prueba: «¿cuál es el estado de la factura 53380?»</p>}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="bubble">{m.content}</div>
            {m.tool_calls?.map((c, j) => (
              <details key={j} className="toolcall">
                <summary>{c.name}({JSON.stringify(c.args)})</summary>
                <pre>{JSON.stringify(c.result, null, 2)}</pre>
              </details>
            ))}
          </div>
        ))}
        {sending && <div className="msg assistant"><div className="bubble typing">pensando…</div></div>}
      </div>
      <div className="composer">
        <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} placeholder="Escribe un mensaje…" />
        <button className="btn primary" onClick={send} disabled={sending}>Enviar</button>
      </div>
    </main>
  );
}

/* ----------------------------- Configuración ---------------------------- */
function SettingsTab({ onSaved, setError }) {
  const [s, setS] = useState(null);
  const [models, setModels] = useState({ ollama: [], openai: [] });
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api("/api/settings").then(setS).catch((e) => setError(e.message));
    api("/api/models").then(setModels).catch(() => {});
  }, []);

  if (!s) return <main className="panel"><p className="muted">Cargando…</p></main>;

  const set = (k, v) => { setS({ ...s, [k]: v }); setSaved(false); };
  const suggestions = s.provider === "openai" ? models.openai : models.ollama;

  const save = async () => {
    try {
      const body = { ...s };
      if (!body.openai_api_key) delete body.openai_api_key; // no pisar con vacío
      const res = await api("/api/settings", { method: "PUT", body: JSON.stringify(body) });
      setS(res); setSaved(true); onSaved();
    } catch (e) { setError(e.message); }
  };

  return (
    <main className="panel settings">
      <h2>Configuración del modelo</h2>

      <div className="field">
        <label>Proveedor</label>
        <div className="segmented">
          <button className={s.provider === "ollama" ? "on" : ""} onClick={() => set("provider", "ollama")}>Ollama (local)</button>
          <button className={s.provider === "openai" ? "on" : ""} onClick={() => set("provider", "openai")}>OpenAI / API</button>
        </div>
      </div>

      <div className="field">
        <label>Modelo</label>
        <input list="modellist" value={s.model} onChange={(e) => set("model", e.target.value)} placeholder={s.provider === "openai" ? "gpt-4o-mini" : "qwen3:8b"} />
        <datalist id="modellist">{suggestions.map((m) => <option key={m} value={m} />)}</datalist>
        {s.provider === "ollama" && models.ollama.length > 0 && (
          <p className="muted small">Instalados: {models.ollama.join(", ")}</p>
        )}
      </div>

      {s.provider === "openai" ? (
        <>
          <div className="field">
            <label>API key {s.openai_api_key_set && <small>— ya hay una guardada (déjala vacía para conservarla)</small>}</label>
            <input type="password" value={s.openai_api_key || ""} onChange={(e) => set("openai_api_key", e.target.value)} placeholder={s.openai_api_key_set ? "•••••••• (guardada)" : "sk-..."} />
          </div>
          <div className="field">
            <label>Base URL <small>— cámbiala para otra API compatible (Groq, OpenRouter, etc.)</small></label>
            <input value={s.openai_base_url} onChange={(e) => set("openai_base_url", e.target.value)} placeholder="https://api.openai.com/v1" />
          </div>
        </>
      ) : (
        <div className="field">
          <label>Ollama host <small>— avanzado</small></label>
          <input value={s.ollama_host} onChange={(e) => set("ollama_host", e.target.value)} placeholder="http://ollama:11434" />
        </div>
      )}

      <div className="grid3">
        <div className="field"><label>num_ctx</label><input type="number" value={s.num_ctx} onChange={(e) => set("num_ctx", +e.target.value)} /></div>
        <div className="field"><label>num_predict</label><input type="number" value={s.num_predict} onChange={(e) => set("num_predict", +e.target.value)} /></div>
        <div className="field">
          <label>Razonamiento (think)</label>
          <label className="chk big"><input type="checkbox" checked={!!s.think} onChange={(e) => set("think", e.target.checked)} /> {s.think ? "activo" : "apagado"}</label>
        </div>
      </div>
      {s.provider === "ollama" && s.think && <p className="hint">Con qwen3, activar el razonamiento sube mucho la latencia (no recomendado para voz).</p>}

      <div className="actions">
        <button className="btn primary" onClick={save}>Guardar</button>
        {saved && <span className="savedok">✓ Guardado — aplica a las próximas llamadas</span>}
      </div>
    </main>
  );
}
