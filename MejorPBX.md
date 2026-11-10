# Plan de mejoras — PBX IA

> **Documento de trabajo para Claude Code.** Es autocontenido: asume que no viste las
> conversaciones previas. Trabaja **por áreas y de arriba hacia abajo**. No marques una
> tarea como hecha hasta cumplir su **criterio de aceptación**. Si una decisión es
> irreversible o ambigua, para y pregunta antes de ejecutar.

Repo: `Ascencioncar/PBX_IA` — agente de voz para PBX (STT faster-whisper + LLM Ollama con
tool calling + TTS Kokoro, puente AudioSocket con Asterisk, webui FastAPI+React).

---

## 0. Principios que NO se rompen

1. **Config-driven.** Nada de rutas, puertos, IPs, modelos o credenciales hardcodeados.
   Todo por `.env`, `data/tools.json` o `data/settings.json`.
2. **Portabilidad.** El objetivo de producción es un **Mac Studio M5 Max (Apple Silicon)**
   que además correrá otros proyectos. No acoplar nada al equipo Windows/WSL del lab.
3. **No romper las fases existentes.** El CLI de texto, el pipeline de voz y el loop
   AudioSocket deben seguir funcionando tras cada cambio.
4. **Cambios incrementales y verificables.** Un PR por tarea (o por grupo pequeño),
   con su criterio de aceptación probado.
5. **El agente de voz y la webui comparten `data/tools.json` y `data/settings.json`.**
   Cualquier cambio en el modelo de datos debe mantener esa compatibilidad.

### Convención de commits
Termina cada mensaje de commit con:
```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```
Y las descripciones de PR con:
```
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## ÁREA A — Infraestructura, latencia y robustez del backend

Orden por impacto. **A1 es la tarea de mayor retorno de todo el documento.**

### A1 · Streaming de TTS por frases  🔴 PRIORIDAD MÁXIMA
**Problema:** `telephony/audiosocket_server.py::_speak()` sintetiza la respuesta COMPLETA
antes de mandar el primer frame de audio. Hoy el llamante espera ~14 s en silencio.

**Qué hacer:**
- Trocear la respuesta del agente por frases (`.`, `?`, `!`, `…`) y empezar a sintetizar
  y enviar la **primera frase** mientras se generan las siguientes.
- Kokoro tiene RTF ≈ 0.35 ⇒ el primer audio debe salir en **< 1 s**.
- Idealmente combinar con **stream del LLM** (ver A2): emitir tokens de Ollama con
  `stream=True`, cortar por frase y alimentar el TTS de esa frase sin esperar al resto.

**Archivos:** `telephony/audiosocket_server.py`, `agent/llm.py` (añadir variante streaming
que no rompa la API actual `run_conversation`), `agent/tts.py`.

**Criterio de aceptación:** medir *time-to-first-audio* (TTFA) en el loop completo y que baje
de ~14 s a **< 2 s**. Registrar la métrica en el benchmark (`agent/voice_pipeline.py --bench`).

---

### A2 · Stream del LLM + barge-in (interrupción)
**Problema:** (a) el LLM se consume de golpe; (b) en `_drain()` se descarta el audio del
llamante mientras el agente habla ⇒ no se puede interrumpir.

**Qué hacer:**
- Variante de `run_conversation` que haga *stream* de tokens de Ollama y rinda frases.
- **Barge-in:** escuchar con VAD **durante** la reproducción; si el llamante habla,
  cortar el `_speak` en curso y pasar a escuchar. Hacerlo opcional vía `.env`
  (`BARGE_IN=true`).

**Archivos:** `agent/llm.py`, `telephony/audiosocket_server.py`, `agent/config.py`.

**Criterio de aceptación:** con `BARGE_IN=true`, hablar encima del agente corta su audio en
< 300 ms y procesa el nuevo turno. Sin la bandera, comportamiento actual intacto.

---

### A3 · Recorte de historial (evitar deriva de latencia)
**Problema:** en `CallHandler.handle` se hace `messages.append(...)` por turno y por
resultado de herramienta, sin recortar nunca ⇒ en llamadas largas el contexto puede
superar `num_ctx=8192` y la latencia sube turno a turno.

**Qué hacer:** ventana deslizante que conserve el `system` + los últimos N turnos
(configurable, p. ej. `HISTORY_MAX_TURNS=8`). Los resultados de herramientas antiguos se
resumen o descartan.

**Archivos:** `telephony/audiosocket_server.py`, `agent/llm.py`, `agent/config.py`.

**Criterio de aceptación:** una llamada simulada de 20+ turnos mantiene latencia de LLM
estable (sin crecimiento monótono) y nunca excede `num_ctx`.

---

### A4 · Manejo de errores del bucle de llamada + respuesta de respaldo
**Problema:** `handle()` solo captura `ConnectionError/OSError`. Si `run_conversation`
lanza (p. ej. `ollama.ResponseError` a mitad del loop), el hilo de la llamada muere en
silencio y el llamante queda colgado sin explicación.

**Qué hacer:** envolver la generación de respuesta en `try/except`; ante fallo, sintetizar
una frase de respaldo (*"Disculpa, tuve un problema, ¿puedes repetir?"*) y continuar la
llamada en vez de cortarla.

**Archivos:** `telephony/audiosocket_server.py`.

**Criterio de aceptación:** forzar un error del LLM (mock) a mitad de llamada y verificar
que el agente dice la frase de respaldo y sigue atendiendo.

---

### A5 · Topes de turno/llamada + soporte DTMF
**Problema:** `_listen` no tiene duración máxima de turno ni de llamada (ruido continuo hace
crecer el buffer). Y se ignora `T_DTMF`, pese a que Whisper confunde números dictados
(*"53380" → "53.380"*).

**Qué hacer:**
- `MAX_UTTERANCE_MS` y `MAX_CALL_SECONDS` configurables; al excederlos, cerrar turno/llamada
  con limpieza.
- Manejar `T_DTMF`: acumular dígitos y exponerlos al agente (p. ej. permitir que el usuario
  teclee el número de factura por el keypad). Documentar el flujo en `data/MANUAL`.

**Archivos:** `telephony/audiosocket_server.py`, `agent/config.py`.

**Criterio de aceptación:** una llamada que supera `MAX_CALL_SECONDS` se cierra limpia;
teclear dígitos en el softphone los hace llegar al agente como entrada.

---

### A6 · Observabilidad: logging estructurado + métricas de latencia
**Problema:** todo es `print()`. El `T_UUID` que envía AudioSocket se recibe y se descarta.
Sin correlación ni métricas, depurar una llamada en campo es a ciegas.

**Qué hacer:**
- Logging estructurado (JSON o `logging` con formato), con **`call_id`** derivado del
  `T_UUID` en cada línea.
- Métricas por etapa (STT / LLM / TTS / TTFA) por turno, exportables (log y/o endpoint).
- Opcional: persistir transcripción de cada llamada en `data/calls/` (configurable; apagado
  por defecto por privacidad).

**Archivos:** `telephony/audiosocket_server.py`, nuevo `agent/logging.py` o similar.

**Criterio de aceptación:** los logs de una llamada se pueden filtrar por `call_id` y
muestran latencia por etapa. La webui (Área B) puede leer esas métricas.

---

### A7 · Dependencias: una sola fuente, con versiones fijadas
**Problema:** los tres `Dockerfile*` repiten dependencias *inline* en vez de instalar desde
`requirements.txt`, y los pins ya divergen (`openai` está en los Dockerfiles pero no en
`requirements.txt`). Todo es `>=`, sin lockfile ⇒ builds no reproducibles.

**Qué hacer:**
- Consolidar en `requirements.txt` (o separar `requirements-core.txt` / `requirements-voice.txt`
  / `requirements-webui.txt` si conviene por imagen).
- **Fijar versiones** (pin exacto o lockfile con `uv`/`pip-tools`).
- Que todos los `Dockerfile*` hagan `pip install -r <requirements>`.
- Añadir usuario no-root en los contenedores (hardening).

**Archivos:** `requirements*.txt`, `Dockerfile`, `Dockerfile.voice`, `Dockerfile.webui`.

**Criterio de aceptación:** `docker compose build` reproducible; no hay dependencias
declaradas en dos sitios; los contenedores no corren como root.

---

### A8 · Seguridad del dispatch (SSRF) — coordinar con B1
**Problema:** `agent/tools.py::dispatch()` ejecuta método + URL + cabeceras arbitrarios.
Con la webui sin auth (hoy), cualquiera en la LAN puede crear una herramienta que apunte a
servicios internos o a un servidor externo con `auth=bearer` y **robar `TOOLS_API_KEY`**.

**Qué hacer:**
- Allowlist opcional de hosts/esquemas (`TOOLS_ALLOWED_HOSTS`), bloqueo de IPs privadas /
  metadata (`169.254.169.254`, `127.0.0.0/8`, etc.) salvo que se habilite explícitamente.
- Corregir el bug cosmético: en `dispatch()` el parámetro `name` se pisa dentro del loop de
  cabeceras (`name = (h.get("name")...)`). Renombrar la variable local a `hname`.

**Archivos:** `agent/tools.py`, `agent/config.py`.

**Criterio de aceptación:** una herramienta que apunta a una IP privada/metadata es
rechazada cuando la allowlist está activa; el bug de shadowing desaparece.

---

### A9 · Tests automatizados + CI
**Problema:** no hay tests (`test_client.py` es un cliente manual) ni CI.

**Qué hacer:**
- `pytest` con unit tests de funciones puras de alto valor:
  `tools.dispatch` (armado de URL, routing path/query/body, modo simulado, allowlist),
  `llm._extract_tool_calls`, `tts.clean_for_tts`, `audiosocket._is_farewell`,
  `settings.load/save` (merge).
- Config de `ruff` (lint + format).
- Workflow de GitHub Actions: `lint` + `pytest` + `docker build` en cada push/PR.

**Archivos:** nuevo `tests/`, `pyproject.toml` (ruff/pytest), `.github/workflows/ci.yml`.

**Criterio de aceptación:** `pytest` verde en local y en CI; `ruff check` sin errores;
el workflow corre en GitHub.

---

## ÁREA B — Frontend / webui: que parezca un PBX real

Hoy la webui (`webui/app.py` + `webui/frontend/`) es funcional pero mínima: CRUD de
herramientas, chat de prueba y ajustes, **sin autenticación** y con todo en una sola vista.
Objetivo: convertirla en un **panel de administración tipo PBX**, con login, navegación
clara y un flujo pulido para **probar APIs y convertirlas en herramientas del agente**.

### B1 · Autenticación / inicio de sesión  🔴
**Problema:** la API FastAPI no tiene auth y se expone en `:8000`. Cualquiera en la red
puede hacer CRUD de herramientas (y, vía *Probar*, ejecutar peticiones con la API key).

**Qué hacer:**
- Login real pero sencillo (es una herramienta de admin, no sobre-ingeniería):
  usuario+contraseña con hash (bcrypt/argon2), credenciales iniciales por `.env`
  (`WEBUI_USER`, `WEBUI_PASSWORD_HASH`), sesión por cookie firmada o token JWT corto.
- Middleware que protege **todas** las rutas `/api/*` salvo el login.
- Pantalla de login en React; manejo de sesión expirada; botón de logout.
- Rate limiting básico en el login.

**Archivos:** `webui/app.py` (auth + middleware), nuevo `webui/auth.py`,
`webui/frontend/src/` (vista Login, estado de sesión), `.env.example`.

**Criterio de aceptación:** sin sesión válida, `/api/*` responde 401 y la UI redirige a
login. Con credenciales correctas se entra y la sesión persiste.

---

### B2 · Enmascarar secretos en la API
**Problema:** `GET /api/tools` devuelve los `headers` (API keys de servicios externos) en
**texto plano**. La UI los enmascara en preview, pero el endpoint los sirve tal cual.

**Qué hacer:** enmascarar valores de cabeceras sensibles al listar (`••••••`), y aceptar un
marcador "sin cambios" al guardar para no sobre-escribir con vacío (igual que ya se hace con
`openai_api_key` en `settings`). No devolver nunca secretos completos por la API de lectura.

**Archivos:** `webui/app.py`, `agent/tools.py`, `webui/frontend/src/App.jsx`.

**Criterio de aceptación:** ningún endpoint de lectura devuelve el valor completo de una
cabecera sensible; editar una herramienta sin tocar la cabecera conserva el valor guardado.

---

### B3 · Reestructura general (navegación tipo panel PBX)
**Problema:** todo vive en una barra de pestañas plana (`tools` / `chat` / `settings`).

**Qué hacer:** rediseñar la navegación como un panel de administración con secciones:
- **Dashboard:** estado de servicios (Ollama/agente/audiosocket/asterisk), modelo activo,
  nº de herramientas, métricas de latencia recientes (de A6), llamadas activas.
- **Herramientas / APIs:** el núcleo (ver B4).
- **Extensiones / Telefonía:** vista de solo-lectura o editable del dialplan y endpoints
  SIP (extensión 100 → agente, 600 → eco, estado de registro del softphone). Sin exponer
  secretos.
- **Modelo / Agente:** lo que hoy es "Configuración" (proveedor, modelo, num_ctx, think…),
  más el `SYSTEM_PROMPT` editable desde la UI (guardado en `data/`).
- **Chat de prueba:** como hoy, mostrando qué herramienta invoca y su resultado.

Aplicar el skill de diseño frontend para que se vea intencional (no plantilla genérica):
tema claro/oscuro, estados de carga/error consistentes, responsive.

**Archivos:** `webui/frontend/src/` (router + vistas), `webui/frontend/src/styles.css`,
`webui/app.py` (endpoints nuevos: estado de servicios, system prompt).

**Criterio de aceptación:** navegación por secciones; el Dashboard refleja el estado real
del sistema; el `SYSTEM_PROMPT` se edita y persiste sin tocar código.

---

### B4 · Gestión de APIs → herramientas del agente (flujo estrella)
Esto es lo que más le importa al usuario: **configurar una API, probarla desde la interfaz,
y que quede registrada como herramienta que el agente puede invocar.** La base ya existe
(`data/tools.json` + editor + endpoint `/test`); hay que pulir el flujo y la UX.

**Qué hacer:**
- Asistente de alta de API claro: método, URL (con `{base}` y `{param}` de path), auth
  (none/bearer o cabeceras propias), parámetros (nombre, tipo, ubicación path/query/body,
  requerido, descripción — recordar que el modelo usa la descripción para decidir cuándo
  llamarla).
- **Probar la API dentro de la UI** con valores de ejemplo y ver la petición real
  (preview) + la respuesta cruda, distinguiendo claramente estados **OK / SIMULADO / ERROR**
  (ya existe `estado` en `dispatch`; mejorar presentación: código HTTP, tiempos, body).
- Al guardar, la API queda como **herramienta del agente** automáticamente (ya comparten
  `tools.json`). Mostrar de forma explícita "esta API ya está disponible para el agente".
- Validaciones que hoy son warnings (path param sin declarar, etc.) mantenerlas y mejorarlas.
- Import/export del set de herramientas (ya existe) — conservarlo.
- Opcional: probar la herramienta **a través del agente** ("pregúntale al agente algo que
  deba usar esta API") y mostrar el `tool_call` resultante.

**Archivos:** `webui/frontend/src/` (editor/asistente de API), `webui/app.py`
(`/api/tools/{name}/test` enriquecido con tiempos y código HTTP), `agent/tools.py`.

**Criterio de aceptación:** un usuario no técnico puede, desde la UI: crear una API, probarla
con datos de ejemplo, ver la respuesta, guardarla, e inmediatamente el agente la usa en el
chat de prueba — sin tocar archivos ni reiniciar.

---

### B5 · Pulido UX
- Estados de carga/vacío/error consistentes en todas las vistas.
- Confirmaciones destructivas (borrar herramienta) ya existen; revisarlas.
- Accesibilidad básica (labels, foco, contraste en claro/oscuro).

**Criterio de aceptación:** recorrido completo sin estados rotos; pasa una revisión visual
en claro y oscuro.

---

## ÁREA C — Instalación en Mac M5 en un solo comando

**Objetivo:** que montar todo en el Mac Studio M5 (Apple Silicon) sea **un comando**.
Contexto ya resuelto en `docker-compose.mac.yml`: en Mac, **Ollama corre nativo** (Metal +
memoria unificada) y los contenedores le hablan por `host.docker.internal:11434`.

### C1 · Script de instalación `scripts/install-mac.sh`
**Qué debe hacer, idempotente y verboso:**
1. Detectar que es macOS + Apple Silicon (si no, abortar con mensaje claro).
2. Comprobar/instalar prerequisitos: Homebrew, Ollama, Docker (o Colima/OrbStack como
   alternativa a Docker Desktop — decidir y documentar), `espeak-ng`.
3. Arrancar `ollama serve` (si no está) y `ollama pull` del modelo principal y el smoke.
4. Generar `.env` desde `.env.example` si no existe, con valores sensatos para Mac
   (`OLLAMA_HOST=http://host.docker.internal:11434`) y **generar secretos** (contraseña de
   webui hasheada, password SIP) en vez de dejar los de ejemplo.
5. `docker compose -f docker-compose.yml -f docker-compose.mac.yml build && up -d`.
6. Healthcheck final (reutilizar/ampliar `scripts/healthcheck.sh`): GPU/Metal de Ollama,
   modelos, servicios arriba, webui respondiendo en `:8000`.
7. Imprimir resumen: URL de la webui, credenciales iniciales, cómo registrar el softphone.

**Entrega de un solo comando:**
```bash
# Opción A (repo ya clonado):
make mac      # o: ./scripts/install-mac.sh

# Opción B (bootstrap desde cero) — documentar y que el usuario revise el script antes:
./scripts/install-mac.sh
```
Añadir un `Makefile` con objetivos `mac`, `up`, `down`, `logs`, `health`, `test`.

> ⚠️ No hardcodear credenciales en el script ni commitear secretos generados. El `.env`
> queda en `.gitignore` (ya lo está). No ejecutes acciones irreversibles sin avisar.

**Archivos:** nuevo `scripts/install-mac.sh`, `Makefile`, `scripts/healthcheck.sh`
(ampliar), `docs/DESPLIEGUE_MAC.md` (actualizar al nuevo flujo), `.env.example`.

**Criterio de aceptación:** en un Mac M5 limpio, **un solo comando** deja la webui accesible
en `:8000` con login, el agente respondiendo en el chat de prueba, y el healthcheck en verde.
Correr el comando dos veces no rompe nada (idempotente).

---

### C2 · Documentación del despliegue Mac
Actualizar `docs/DESPLIEGUE_MAC.md` con: requisitos, el comando único, qué hace el script,
troubleshooting (Ollama nativo no arranca, Docker/Colima, audio SIP), y nota de que el equipo
es compartido con otros proyectos (el PBX usa <25 GB de RAM incluso con carga alta).

---

## Orden de ejecución sugerido (milestones)

1. **M1 — Latencia (lo que convierte el demo en usable):** A1 → A2 → A3 → A4.
2. **M2 — Robustez y base de ingeniería:** A5 → A6 → A7 → A8 → A9.
3. **M3 — Webui tipo PBX:** B1 → B2 → B3 → B4 → B5.
4. **M4 — Instalación Mac de un comando:** C1 → C2.

> Regla de secuencia: **no empieces el Área B ni C hasta cerrar A1** (streaming de TTS).
> Es la mejora de mayor impacto y valida el resto del pipeline.

---

## Checklist global de aceptación

- [ ] TTFA (time-to-first-audio) < 2 s en el loop completo.
- [ ] Barge-in funcional (bandera `.env`).
- [ ] Latencia estable en llamadas largas (recorte de contexto).
- [ ] Ningún fallo del LLM corta la llamada sin frase de respaldo.
- [ ] Topes de turno/llamada + DTMF operativos.
- [ ] Logs por `call_id` con métricas de latencia por etapa.
- [ ] Dependencias en una sola fuente, fijadas; contenedores no-root.
- [ ] Dispatch con allowlist anti-SSRF; bug de shadowing corregido.
- [ ] `pytest` + `ruff` + CI en verde.
- [ ] Webui con login; `/api/*` protegido.
- [ ] Secretos de cabeceras nunca devueltos en claro.
- [ ] Navegación tipo panel PBX (Dashboard, Herramientas, Telefonía, Modelo, Chat).
- [ ] Flujo completo: crear API → probarla en la UI → queda como herramienta → el agente la usa.
- [ ] `./scripts/install-mac.sh` (o `make mac`) monta todo en un Mac M5 limpio, idempotente.