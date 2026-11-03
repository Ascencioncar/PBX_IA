# PBX con agente de IA — plan de montaje (entorno de PRUEBAS)

> Documento de trabajo para Claude Code. Es **autocontenido**: asume que no viste la
> conversación previa. Trabaja **por fases, de arriba hacia abajo**, y **no avances a la
> siguiente fase hasta cumplir el criterio de aceptación** de la actual. La telefonía (Fase 3)
> no se toca hasta que el bucle de voz local (Fase 2) funcione.

---

## 0. Objetivo

Montar, en **este equipo Linux**, un agente de voz con IA que:

1. Conteste llamadas telefónicas a través de un **Asterisk de laboratorio** (instancia nueva, **no** el Elastix de producción).
2. Mantenga una conversación **hablada en español**.
3. **Resuelva tareas llamando a herramientas** que el usuario le entrega: sus propias **APIs / webhooks** (tool calling / function calling).

**Estado final de esta etapa:** registrar un softphone al Asterisk local, marcar una extensión,
y conversar por voz con el agente, que es capaz de invocar herramientas HTTP y usar su resultado
en la respuesta.

Esto es el entorno de **pruebas**. Producción se montará después en un **Mac Studio M5 Max (128 GB)**;
por eso hay una sección de portabilidad (§9) — no acoplar nada a esta máquina.

---

## 1. Arquitectura

Un "PBX con IA" no es un solo modelo, es una **tubería**:

```
Softphone ──SIP──> Asterisk (PBX pruebas) ──AudioSocket──> Orquestador (Python)
                                                              │
                                 audio ──> STT (faster-whisper) ──> texto
                                                              │
                                 texto ──> LLM (Ollama + TOOLS) ──> decide / llama API-webhook
                                                              │
                                 texto ──> TTS (Piper) ──> audio ──> de vuelta a Asterisk ──> llamante
```

El LLM de Ollama es solo el "cerebro". Alrededor van STT (voz→texto), TTS (texto→voz) y el
**registro de herramientas** (las APIs/webhooks del usuario) que el cerebro invoca.

---

## 2. Hardware y restricciones

- **CPU:** Ryzen 7 5800X (8c/16t). **RAM:** 32 GB. Sobra para orquestador + PBX + STT/TTS en CPU.
- **GPU:** RTX 3070 Ti, **8 GB VRAM** → **este es el cuello de botella.** Reparto:
  - **LLM** → GPU.
  - **STT (faster-whisper `small`)** → GPU si cabe (int8_float16), si no → CPU.
  - **TTS (Piper)** → CPU siempre (es ligerísimo).
- faster-whisper en GPU necesita **driver NVIDIA + CUDA 12 + cuDNN 9**. Si da problemas de cuDNN,
  caer a CPU (`device="cpu"`) — el 5800X lo mueve, solo añade latencia.

**Primeros pasos obligatorios (Fase 0):** confirmar SO y GPU:

```bash
uname -a && (lsb_release -a 2>/dev/null || cat /etc/os-release)
nvidia-smi                 # debe listar la 3070 Ti y la versión de CUDA
```

Si `nvidia-smi` no existe o falla, instalar el driver NVIDIA antes de seguir.

---

## 3. Stack técnico (y por qué)

| Pieza | Elección | Nota |
|------|----------|------|
| LLM | **Ollama** | runtime local, API HTTP, buen soporte de tool calling |
| Modelo principal | **`qwen3:8b`** | fuerte en tool calling y en español; ~5 GB en Q4, cabe en 8 GB |
| Modelo smoke test | **`llama3.2:3b`** | rápido, para validar el flujo antes de nada |
| Modelo alt. baja latencia | **`gemma4:e4b`** | más pequeño, deja VRAM para Whisper en GPU |
| STT | **faster-whisper** (CTranslate2) | modelo `small` o `medium`, idioma `es` |
| TTS | **Piper** | voz `es_*` (ej. `es_MX`, `es_ES`), corre en CPU |
| VAD (turnos) | **silero-vad** o **webrtcvad** | detectar cuándo terminó de hablar |
| PBX | **Asterisk ≥ 18** (ideal 20/22 LTS) | instancia **nueva** de laboratorio, **en Docker** (red host) — §7.1 |
| Puente audio | **AudioSocket** (o ARI external media) | Asterisk ↔ orquestador |
| Orquestador | **Python 3.11+** | pega todo |

> **Cuantización:** usar **Q4_K_M**. No bajar a Q2/Q3 (degrada el tool calling).
> **Contexto:** mantener `num_ctx` modesto (4096–8192) para ahorrar VRAM.

---

## 4. Contrato de herramientas (tool calling) — ES LO CENTRAL

Una "herramienta" = una función con **JSON Schema** que se pasa a Ollama. Cuando el modelo decide
usarla, devuelve `tool_calls`; el orquestador **ejecuta la llamada HTTP real** (la API/webhook del
usuario) y devuelve el resultado al modelo como mensaje con `role: "tool"`. El modelo continúa con
ese dato.

**Diseño:** el registro de herramientas debe estar **desacoplado** en un solo módulo
(`agent/tools.py`) o archivo de config, para que el usuario agregue sus endpoints sin tocar el
resto. La URL base y las credenciales van por variables de entorno, **nunca hardcodeadas**.

**Formato del schema que espera Ollama (array `tools`):**

```json
{
  "type": "function",
  "function": {
    "name": "consultar_factura",
    "description": "Consulta el estado de una factura por su número.",
    "parameters": {
      "type": "object",
      "properties": {
        "numero": { "type": "string", "description": "Número de factura, p. ej. 53380" }
      },
      "required": ["numero"]
    }
  }
}
```

**Bucle del orquestador (pseudocódigo, Python):**

```python
messages = [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text}]

while True:
    resp = ollama.chat(model=MODEL, messages=messages, tools=TOOLS)
    msg = resp["message"]
    messages.append(msg)
    tool_calls = msg.get("tool_calls")
    if not tool_calls:
        break                      # respuesta final en msg["content"]
    for call in tool_calls:
        name = call["function"]["name"]
        args = call["function"]["arguments"]      # dict
        result = dispatch(name, args)             # ← ejecuta HTTP a la API/webhook del usuario
        messages.append({"role": "tool", "name": name,
                         "content": json.dumps(result, ensure_ascii=False)})
```

> Verificar los nombres exactos de campos (`tool_calls`, `arguments`, `role: "tool"`, `name`/`tool_name`)
> contra la versión instalada de la librería `ollama` de Python; han variado entre versiones.

**Herramientas de ejemplo (placeholders):** implementar dos como demostración, pegando a una URL
base configurable (`TOOLS_BASE_URL`), con los endpoints reales marcados como **TODO del usuario**
(§10):

- `consultar_factura(numero)` → `GET {TOOLS_BASE_URL}/facturas/{numero}`
- `crear_ticket(asunto, descripcion)` → `POST {TOOLS_BASE_URL}/tickets` (JSON)

`dispatch()` enruta por nombre, hace la petición con `httpx`/`requests`, maneja timeout y errores,
y devuelve un dict serializable. Si el endpoint real aún no existe, devolver una respuesta
simulada clara (p. ej. `{"estado": "SIMULADO", ...}`) para no bloquear las pruebas.

---

## 5. FASE 1 — LLM + herramientas (solo texto)

Validar el cerebro aislado, **sin audio ni telefonía**.

**Tareas**
- Instalar Ollama y descargar modelos:
  ```bash
  curl -fsSL https://ollama.com/install.sh | sh
  ollama pull llama3.2:3b     # smoke test
  ollama pull qwen3:8b        # principal
  # opcional: ollama pull gemma4:e4b
  ```
- Verificar que el modelo corre en GPU:
  ```bash
  ollama run qwen3:8b "responde solo: ok"
  ollama ps        # debe mostrar el modelo con % en GPU
  ```
- Crear entorno Python y dependencias base (`ollama`, `httpx`, `python-dotenv`).
- Implementar `agent/tools.py` (registro + `dispatch`) y un **CLI** `agent/chat_cli.py` que corra
  el bucle de §4 con un `SYSTEM_PROMPT` en español (rol: asistente telefónico de la empresa,
  conciso, usa herramientas cuando aplique).

**Criterio de aceptación**
- Escribo "¿cuál es el estado de la factura 53380?" y el modelo **invoca `consultar_factura`** con
  `numero="53380"`, el `dispatch` hace la llamada HTTP (real o simulada) y el modelo **incorpora el
  resultado** en una respuesta en español.
- Una petición que no requiere herramienta se responde directo, sin inventar llamadas.

---

## 6. FASE 2 — Bucle de voz local (micrófono/altavoz, sin telefonía)

**Tareas**
- Dependencias: `faster-whisper`, `piper-tts` (o binario de Piper), `silero-vad` o `webrtcvad`,
  `sounddevice`/`pyaudio`.
- STT:
  ```python
  from faster_whisper import WhisperModel
  model = WhisperModel("small", device="cuda", compute_type="int8_float16")
  # fallback: device="cpu", compute_type="int8"
  segments, info = model.transcribe(audio_16k, language="es", vad_filter=True)
  ```
- TTS con Piper (voz en español; descargar un `.onnx` es_* del repo de voces de Piper):
  ```bash
  echo "hola, ¿en qué puedo ayudarte?" | piper -m es_MX-xxxx.onnx -f /tmp/out.wav
  ```
- Ensamblar el loop: **mic → VAD (fin de habla) → faster-whisper → agente (Fase 1) → Piper → altavoz.**
  Para la primera versión vale **pulsar-para-hablar**; el VAD/barge-in se refina después.

**Criterio de aceptación**
- Conversación **hablada en español** de ida y vuelta, con **tool calling** funcionando igual que
  en Fase 1.
- Medir y anotar latencias: tiempo de STT, tiempo a primer token del LLM, tiempo de TTS. Dejarlo
  en un `BENCHMARKS.md`. Si molesta la latencia, probar `gemma4:e4b` y/o Whisper `small` en vez de `medium`.

---

## 7. FASE 3 — Asterisk de laboratorio + conectar el agente

> Instancia **nueva** de Asterisk en esta máquina. **No** tocar el Elastix de producción.

### 7.1 Levantar Asterisk en Docker (recomendado para el lab)

En **Linux**, Docker con **`network_mode: host`** es la vía más limpia: evita el lío de NAT con los
puertos RTP dinámicos (SIP y media funcionan sin mapear rangos de puertos) y deja que el contenedor
hable con el agente del host por `127.0.0.1`.

> El aviso previo de "no correr el PBX en Docker" era para **macOS/producción** (la VM de red de
> Docker en Mac estropea el RTP). En **este equipo Linux de pruebas**, Docker con red host es
> perfectamente válido.

`telephony/docker-compose.yml`:
```yaml
services:
  asterisk:
    # Imagen de Asterisk >=18 (p. ej. mlan/asterisk o andrius/asterisk).
    # VERIFICAR que incluye res_audiosocket; si no, usar el Dockerfile de respaldo.
    image: mlan/asterisk:latest
    container_name: pbx-lab
    network_mode: host            # SOLO Linux: SIP/RTP y loopback al agente del host, sin NAT
    volumes:
      - ./asterisk/pjsip.conf:/etc/asterisk/pjsip.conf:ro
      - ./asterisk/extensions.conf:/etc/asterisk/extensions.conf:ro
    restart: unless-stopped
```

Arrancar y verificar AudioSocket dentro del contenedor:
```bash
cd telephony && docker compose up -d
docker exec -it pbx-lab asterisk -rx "core show version"
docker exec -it pbx-lab asterisk -rx "module show like audiosocket"      # res_audiosocket.so + app_audiosocket.so
docker exec -it pbx-lab asterisk -rx "core show application AudioSocket"  # ← confirmar el ORDEN de args
```

> **Si la imagen no trae `res_audiosocket.so`** o el tag no es Asterisk >=18, usar el archivo de
> respaldo `telephony/Dockerfile` (`FROM debian:stable` + Asterisk >=18, por paquete o compilado con
> el módulo `res_audiosocket` habilitado). No depender de un solo tag de terceros.
>
> El dialplan de §7.3 usa `uuidgen`; si la imagen no lo incluye, instalar `util-linux` en ella o
> fijar un UUID de prueba en el dialplan.

Recargar config tras editar los `.conf`: `docker exec -it pbx-lab asterisk -rx "core reload"`.

**Alternativa sin Docker (bare-metal):**
```bash
sudo apt update && sudo apt install -y asterisk    # si el repo trae < 18, compilar desde fuente
sudo asterisk -rx "module show like audiosocket"
sudo asterisk -rx "core show application AudioSocket"
```

### 7.2 Softphone por PJSIP (extensión 1001)
`/etc/asterisk/pjsip.conf` (mínimo de laboratorio; cambiar la contraseña):
```ini
[transport-udp]
type=transport
protocol=udp
bind=0.0.0.0:5060

[1001]
type=endpoint
context=from-internal
disallow=all
allow=ulaw
allow=alaw
auth=1001
aors=1001

[1001]
type=auth
auth_type=userpass
username=1001
password=CAMBIAR_ESTO

[1001]
type=aor
max_contacts=1
```

### 7.3 Dialplan: enrutar una extensión al agente vía AudioSocket
`/etc/asterisk/extensions.conf`:
```ini
[from-internal]
exten => 100,1,Answer()
 same => n,Set(UUID=${SHELL(uuidgen | tr -d '\n')})
 same => n,AudioSocket(${UUID},127.0.0.1:9000)   ; ← verificar orden de args con 'core show application AudioSocket'
 same => n,Hangup()
```
Recargar: `sudo asterisk -rx "core reload"`.

### 7.4 Conectar el orquestador — dos caminos

**Camino A (recomendado): partir de un proyecto mantenido.** Evita reimplementar el puente de
audio. Elastix = FreePBX = Asterisk por debajo, así que encajan proyectos como
**`asterisk-ai-voice-agent`** (PyPI / repo `ictinnovations/asterisk-ai-voice-agent`) o **AVA /
`hkjarral/Asterisk-AI-Voice-Agent`**, que ya traen puente AudioSocket/ARI y soporte de **Ollama +
tool calling**. Pasos:
- Clonar, leer su README, configurarlo para: STT=faster-whisper local, LLM=Ollama (`OLLAMA_HOST`,
  modelo `qwen3:8b`), TTS=Piper.
- **Reusar el mismo registro de herramientas de §4** (portar `tools.py`/los schemas) para no
  duplicar la lógica del agente.

**Camino B (control total): servidor AudioSocket propio.** Implementar un servidor **TCP** en
`127.0.0.1:9000` que hable el protocolo AudioSocket (**verificar contra la doc/fuente de Asterisk**):
tramas de `[1 byte tipo][2 bytes longitud big-endian][payload]`; tipos aprox.: `0x01` UUID (16 B),
`0x10` audio (**PCM slin, 16-bit, mono, 8 kHz**), `0x00` fin. El servidor:
- recibe tramas de audio → **resamplea 8 kHz → 16 kHz** → faster-whisper,
- pasa el texto al agente (Fase 1),
- Piper genera audio → **resamplea 16 kHz → 8 kHz** → envía tramas `0x10` a Asterisk (~20 ms por trama).

> El resampleo 8 kHz ↔ 16 kHz es obligatorio (Whisper/Piper trabajan a 16 kHz; AudioSocket suele ir
> a 8 kHz — confirmar). Usar `soxr`/`librosa`/`av` para resamplear.

### 7.5 Probar
- Registrar un softphone (**Zoiper**, **Linphone** o **MicroSIP**) como `1001` contra la IP del equipo.
- Marcar **100** y hablar con el agente.

**Criterio de aceptación**
- Marco 100 desde el softphone y mantengo una conversación por voz con el agente, en español, con
  tool calling funcionando. La telefonía de producción (Elastix) **no se tocó**.

---

## 8. FASE 4 — (FUTURO, fuera de alcance ahora) Puente al Elastix real

No implementar todavía. Cuando toque: crear un **SIP trunk (PJSIP)** entre este PBX de laboratorio
y el Elastix existente, y en Elastix enrutar una extensión/DID específica hacia el trunk del agente.
Mantener el agente en máquina separada reduce el radio de impacto.

---

## 9. Estructura de proyecto sugerida

```
pbx-ia/
├── .env                      # config y secretos (NO commitear)
├── .env.example
├── requirements.txt
├── README.md
├── BENCHMARKS.md             # latencias medidas en Fase 2
├── agent/
│   ├── __init__.py
│   ├── config.py             # lee .env (OLLAMA_HOST, MODEL, TOOLS_BASE_URL, ...)
│   ├── llm.py                # cliente Ollama + bucle de tool calling (§4)
│   ├── tools.py              # registro de herramientas + dispatch (APIs/webhooks del usuario)
│   ├── stt.py                # faster-whisper
│   ├── tts.py                # Piper
│   ├── chat_cli.py           # Fase 1 (texto)
│   └── voice_local.py        # Fase 2 (mic/altavoz)
├── telephony/
│   ├── docker-compose.yml    # Fase 3: Asterisk en Docker (network_mode: host)
│   ├── Dockerfile            # respaldo: Asterisk ≥18 desde fuente si la imagen no trae AudioSocket
│   ├── audiosocket_server.py # Fase 3, camino B (o integración del proyecto del camino A)
│   └── asterisk/             # pjsip.conf / extensions.conf (montados como volúmenes)
└── scripts/
    └── healthcheck.sh        # nvidia-smi, ollama ps, ollama list
```

---

## 10. Configuración (.env)

```ini
# LLM — por HTTP, NO asumir localhost en producción
OLLAMA_HOST=http://127.0.0.1:11434
MODEL=qwen3:8b
NUM_CTX=8192

# STT / TTS
WHISPER_MODEL=small
WHISPER_DEVICE=cuda           # o cpu
WHISPER_COMPUTE=int8_float16  # o int8 en cpu
PIPER_VOICE=/ruta/a/es_MX-xxxx.onnx

# Herramientas del usuario (APIs/webhooks)
TOOLS_BASE_URL=            # TODO usuario
TOOLS_API_KEY=            # TODO usuario (si aplica)

# Telefonía (Fase 3)
AUDIOSOCKET_HOST=127.0.0.1
AUDIOSOCKET_PORT=9000
```

---

## 11. Portabilidad a producción (Mac Studio M5 Max, 128 GB)

Decisiones que Claude Code debe respetar para que esto migre sin rehacerlo:

- **Mismo modelo-familia.** En pruebas `qwen3:8b`; en producción `qwen3:32b` (cabe de sobra en 128 GB
  unificados y es mejor punto calidad/latencia para voz que un 70B). Los schemas de herramientas y
  los prompts se trasladan sin cambios dentro de la familia.
- **El orquestador habla con el LLM por HTTP** (`OLLAMA_HOST`), nunca asume misma máquina. En
  producción el modelo vivirá en el Mac; `OLLAMA_HOST` apuntará a `http://mac-studio:11434`.
- **Asterisk/Elastix se queda en Linux.** No correr el PBX en macOS. El Mac es **servidor de
  inferencia** (y en el Mac vale medir **MLX** vs Ollama por rendimiento).
- **Nada de rutas/puertos/IPs hardcodeados.** Todo por `.env`.

---

## 12. TODOs del usuario (completar)

- [ ] **Endpoints reales** de las APIs/webhooks + método de autenticación → `TOOLS_BASE_URL`, `TOOLS_API_KEY` y los schemas en `agent/tools.py`.
- [ ] **Voz de Piper** elegida en español (`es_MX`, `es_ES`, `es_AR`) → `PIPER_VOICE`.
- [ ] Softphone de pruebas (Zoiper/Linphone/MicroSIP) y contraseña de la extensión 1001.
- [ ] (Fase 4) Datos del Elastix para el SIP trunk.

---

## 13. Checklist global

- [x] Fase 0: SO (Windows 10 + WSL2 Ubuntu-24.04) y `nvidia-smi` OK (host y dentro de Docker). Stack DOCKERIZADO (ver README).
- [x] Fase 1: tool calling en texto, con resultado HTTP incorporado (qwen3:8b, modo simulado). ✅
- [~] Fase 2: pipeline STT+LLM+TTS OK (TTS=**Kokoro-82M** en vez de Piper) + latencias en BENCHMARKS.md. (Hallazgo: apagar `think` de qwen3 bajó el LLM de ~51s a ~7s.)
- [~] Fase 3: Asterisk 22 en Docker + servidor AudioSocket propio (camino B). Loop completo (saludo→STT→LLM+tools→TTS) validado con cliente de prueba y con `originate` a la ext. 100. Falta: softphone real marcando 100. Producción (Elastix) NO tocada.
- [ ] Portabilidad respetada (§11).