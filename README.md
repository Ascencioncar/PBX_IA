# PBX con agente de IA — entorno de pruebas

Agente de voz con IA para PBX. Ver `plan.md` para el diseño completo por fases.

Este montaje está **dockerizado** y corre sobre **WSL2 (Ubuntu-24.04) + Docker Desktop**
con GPU NVIDIA (RTX 3070 Ti). El LLM (Ollama) y el orquestador van en contenedores;
se hablan por la red interna de compose (`http://ollama:11434`).

## Estado

- [x] **Fase 0** — SO (Windows 10 + WSL2) y GPU (`nvidia-smi`, también dentro de Docker) OK.
- [x] **Fase 1** — LLM + tool calling en texto, con resultado HTTP incorporado. ✅
- [~] **Fase 2** — Pipeline de voz STT (faster-whisper) + TTS (**Kokoro-82M**, no Piper) OK y
  latencias medidas (`BENCHMARKS.md`). (El micro/altavoz local se saltó: el audio real llega por SIP.)
- [~] **Fase 3** — Asterisk 22 (Docker) + servidor AudioSocket propio. Loop completo
  (saludo→STT→LLM+tools→TTS) **validado** con cliente de prueba. **Pendiente:** registrar
  un softphone real (1001) y marcar 100.

## Requisitos

- Docker Desktop con backend WSL2 y acceso a GPU (`docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`).
- Un `.env` en la raíz (cópialo de `.env.example`).

## Arranque (Fase 1)

```bash
# 1) Levantar Ollama (GPU) y descargar modelos
docker compose up -d ollama
docker exec pbx-ollama ollama pull llama3.2:3b   # smoke test
docker exec pbx-ollama ollama pull qwen3:8b      # principal

# 2) Construir el agente
docker compose build agent

# 3) Chat interactivo (texto)
docker compose run --rm agent

# 3b) Un solo turno (prueba rápida)
docker compose run --rm -T agent python -m agent.chat_cli --once "estado de la factura 53380"
docker compose run --rm -T agent python -m agent.chat_cli --model llama3.2:3b --verbose --once "hola"
```

Comandos útiles:

```bash
docker exec pbx-ollama ollama ps     # ¿en GPU? (PROCESSOR: %/% CPU/GPU)
docker exec pbx-ollama ollama ls     # modelos instalados
docker compose logs -f ollama
```

## Voz (Fase 2)

STT = faster-whisper (`small`, CPU/int8). TTS = **Kokoro-82M** (CPU, voz `ef_dora`),
elegido sobre Piper (mejor voz, igual de ligero) y sobre VibeVoice (demasiado pesado
para tiempo real). Config en `.env` (`WHISPER_*`, `TTS_*`).

```bash
docker compose build voice
docker compose run --rm voice python -m agent.voice_pipeline --selftest   # TTS<->STT
docker compose run --rm voice python -m agent.voice_pipeline --bench      # latencias
docker compose run --rm voice python -m agent.voice_pipeline --say "hola" --wav-out /app/out.wav
docker compose run --rm voice python -m agent.voice_pipeline --wav-in /app/preg.wav --wav-out /app/resp.wav
```

Ver `BENCHMARKS.md`.

## Telefonía (Fase 3)

Asterisk 22 en Docker + servidor AudioSocket propio (`telephony/audiosocket_server.py`,
servicio `audiosocket`). El dialplan enruta la **extensión 100** al agente.

```bash
docker compose up -d                 # ollama + audiosocket + asterisk
docker logs -f pbx-audiosocket       # ver las llamadas en vivo

# Prueba sin softphone (cliente AudioSocket simulado):
docker compose run --rm -T audiosocket python -m telephony.test_client \
    --text "¿cuál es el estado de la factura 53380?"
```

**Probar con un softphone** (Zoiper / MicroSIP / Linphone, en este mismo PC):

| Campo | Valor |
|---|---|
| Servidor / dominio | `127.0.0.1` (o la IP del equipo en la LAN) |
| Usuario / Auth | `1001` |
| Contraseña | `pbxlab1001` (cambiar en `telephony/asterisk/pjsip.conf`) |
| Puerto | `5060` (UDP) |

- Marca **100** → hablas con el agente.
- Marca **600** → test de eco (diagnóstico de audio sin IA).
- Si registra pero **no hay audio** (RTP), descomenta `external_media_address=127.0.0.1`
  en `pjsip.conf` y `docker exec pbx-asterisk asterisk -rx "core reload"`.

Recargar config de Asterisk tras editar los `.conf`:
`docker exec pbx-asterisk asterisk -rx "core reload"`.

## Herramientas (tool calling) — config-driven

El agente invoca herramientas = APIs/webhooks del usuario. Ahora se definen en
**`data/tools.json`** (no en código) y se editan desde la **interfaz web** (abajo).
El agente de voz y la UI comparten ese archivo; los cambios aplican sin reiniciar.
Mientras `TOOLS_BASE_URL` esté vacío en `.env`, `dispatch()` devuelve respuestas
**SIMULADAS** para no bloquear las pruebas. Ver `plan.md §4`.

## Interfaz web (configurar herramientas) — `localhost:8000`

```bash
docker compose up -d webui
# abre http://localhost:8000
```

- **Herramientas**: crear/editar/borrar. Cada una: método, URL (`{base}` = TOOLS_BASE_URL,
  `{param}` = parámetro de tipo *path*), auth (Bearer usa TOOLS_API_KEY) y parámetros
  (nombre, tipo, ubicación path/query/body, requerido). Botón **Probar** ejecuta el endpoint.
- **Chat de prueba**: habla con el agente por texto y ve **qué herramienta invoca** y su
  resultado, sin llamar por teléfono.
- Rebuild tras tocar el frontend React: `docker compose build webui`.

## Notas de VRAM (8 GB)

`qwen3:8b` + contexto 8192 ≈ 6.6 GB y puede derramar ~18% a CPU. Si la latencia molesta:
baja `NUM_CTX` a 4096 en `.env`, cierra apps que usen GPU, o prueba un modelo más chico.
