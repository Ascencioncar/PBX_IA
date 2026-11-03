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

const EMPTY_TOOL = { name: "", description: "", method: "GET", url: "{base}/", auth: "none", parameters: [] };
const EMPTY_PARAM = { name: "", type: "string", description: "", required: true, location: "query" };
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

  const startNew = () => { setEditing(structuredClone(EMPTY_TOOL)); setIsNew(true); };
  const startEdit = (t) => { setEditing(structuredClone(t)); setIsNew(false); };

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

  return (
    <main className="layout">
      <section className="panel">
        <div className="panel-head">
          <h2>Herramientas <span className="count">{tools.length}</span></h2>
          <button className="btn primary" onClick={startNew}>Nueva</button>
        </div>
        {!info?.tools_base_url_set && (
          <p className="hint">Sin <code>TOOLS_BASE_URL</code> → las pruebas devuelven datos simulados.</p>
        )}
        <div className="cards">
          {tools.length === 0 && <p className="muted">Aún no hay herramientas.</p>}
          {tools.map((t) => (
            <button
              key={t.name}
              className={`toolrow ${editing && !isNew && editing.name === t.name ? "sel" : ""}`}
              onClick={() => startEdit(t)}
            >
              <span className={`tag ${t.method}`}>{t.method}</span>
              <span className="trow-main">
                <b>{t.name}</b>
                <small>{t.description || t.url}</small>
              </span>
              <span className="del" onClick={(e) => { e.stopPropagation(); remove(t.name); }}>✕</span>
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        {editing ? (
          <ToolEditor tool={editing} isNew={isNew} onCancel={() => setEditing(null)} onSave={save} setError={setError} />
        ) : (
          <div className="placeholder">
            <p>Elige una herramienta o crea una nueva.</p>
            <p className="muted">
              Usa <code>{"{base}"}</code> para la URL base y <code>{"{param}"}</code> para parámetros de ruta.
            </p>
          </div>
        )}
      </section>
    </main>
  );
}

function ToolEditor({ tool, isNew, onCancel, onSave, setError }) {
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
          <input value={t.url} onChange={(e) => set("url", e.target.value)} placeholder="{base}/facturas/{numero}" />
        </div>
      </div>
      <div className="field">
        <label>Autenticación</label>
        <select value={t.auth} onChange={(e) => set("auth", e.target.value)}>
          <option value="none">Ninguna</option>
          <option value="bearer">Bearer (usa TOOLS_API_KEY)</option>
        </select>
      </div>

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

      <div className="actions">
        <button className="btn primary" onClick={() => onSave(t, originalName)} disabled={!t.name}>Guardar</button>
        <button className="btn ghost" onClick={onCancel}>Cancelar</button>
      </div>

      <div className="test">
        <div className="subhead"><label>Probar</label></div>
        {t.parameters.map((p) => (
          <div className="field" key={p.name}>
            <label>{p.name} <small>{p.location}</small></label>
            <input value={testArgs[p.name] ?? ""} onChange={(e) => setTestArgs({ ...testArgs, [p.name]: e.target.value })} placeholder={p.description} />
          </div>
        ))}
        <button className="btn" onClick={runTest} disabled={testing || !t.name}>{testing ? "Ejecutando…" : "Ejecutar"}</button>
        {testResult && <pre className="result">{JSON.stringify(testResult, null, 2)}</pre>}
      </div>
    </div>
  );
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
