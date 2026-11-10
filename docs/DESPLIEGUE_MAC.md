# Despliegue en Mac (Apple Silicon M1–M5)

> Entorno objetivo: **macOS en Apple Silicon** (probado para M5, 32 GB).
> Diferencia clave con Windows: **Docker Desktop en Mac NO expone la GPU/Metal**
> a los contenedores. Por eso **Ollama corre NATIVO** (usa Metal y la memoria
> unificada) y el resto de la pila sigue en Docker, hablándole por
> `host.docker.internal:11434`.

---

## 0. Instalación en un comando (recomendado)

Con el repo clonado y **Docker** abierto:

```bash
make mac          # equivale a: ./scripts/install-mac.sh
```

El script es **idempotente** (puedes repetirlo) y hace todo: comprueba macOS/Apple
Silicon, instala Ollama y espeak-ng con Homebrew si faltan, arranca Ollama nativo y
descarga el modelo, genera `.env` con `OLLAMA_HOST=host.docker.internal` y **secretos**
(hash de la contraseña de la webui + secreto de sesión), construye y levanta los
contenedores, y chequea que la webui responda. Al final imprime la **URL, el usuario y la
contraseña** generada.

> La primera vez tarda (descarga el modelo y construye imágenes, torch incluido).
> Acceso luego: <http://localhost:8000> → **login** con las credenciales que imprimió.

Operación: `make up` · `make down` · `make logs` · `make health` · `make test`.

Si prefieres hacerlo a mano, sigue las secciones siguientes.

## 1. Requisitos

- **macOS** en Apple Silicon (M1/M2/M3/M4/M5).
- **Docker Desktop para Mac** instalado y abierto.
- **Homebrew** (para instalar Ollama nativo).
- ~15 GB libres de disco.

Con 32 GB de memoria unificada, `qwen3:8b` va holgado (y cabría un modelo mayor
si quisieras).

---

## 2. Instalar y arrancar Ollama NATIVO

```bash
brew install ollama
ollama serve            # déjalo corriendo (o `brew services start ollama`)
```

En otra terminal, descarga el modelo:

```bash
ollama pull qwen3:8b
# opcional:
ollama pull llama3.2:3b
```

Comprueba que responde en el host:

```bash
curl http://localhost:11434/api/tags      # debe listar los modelos
```

> En Mac el puerto 11434 está libre (el conflicto del 11434 era específico de
> aquel equipo Windows).

---

## 3. Configuración del proyecto

1. Crea el `.env`:
   ```bash
   cp .env.example .env
   ```
2. No hace falta tocar `OLLAMA_HOST`: el override de Mac lo repunta solo.
3. Si traes `data/settings.json` de otro equipo con `ollama_host` fijado a
   `http://ollama:11434`, bórralo o cámbialo a `http://host.docker.internal:11434`
   desde la pestaña *Configuración* (si no existe el archivo, no hagas nada).

---

## 4. Levantar la pila (con el override de Mac)

El proyecto incluye **`docker-compose.mac.yml`**: apaga el contenedor `ollama`
(perfil inactivo), limpia sus dependencias y apunta todos los servicios a
`host.docker.internal:11434`.

```bash
docker compose -f docker-compose.yml -f docker-compose.mac.yml up -d --build
```

> Usa SIEMPRE los dos `-f` en Mac. Para no repetirlos, puedes exportar:
> ```bash
> export COMPOSE_FILE=docker-compose.yml:docker-compose.mac.yml
> docker compose up -d --build      # ya toma ambos
> ```

Arranca `audiosocket`, `asterisk` y `webui` (NO `ollama`, que es nativo).

---

## 5. Verificación

```bash
docker compose -f docker-compose.yml -f docker-compose.mac.yml ps
docker compose -f docker-compose.yml -f docker-compose.mac.yml logs -f audiosocket
```

- **Interfaz web:** <http://localhost:8000> (Ctrl+F5 si ves versión vieja).
- **Chat de prueba:** pestaña *Chat* → *«¿cuál es el estado de la factura 53380?»*.
- Que el agente responda confirma que los contenedores alcanzan el Ollama nativo.

---

## 6. Prueba de voz (softphone)

Igual que en Windows: softphone registrado como `1001` / `pbxlab1001` contra
`127.0.0.1:5060`. Marca `600` (eco) y `100` (agente).

> **Dirección IP:** si vas a conectar un PBX externo (Elastix), averigua la IP de
> la Mac en la LAN con `ipconfig getifaddr en0` y úsala como `GATEWAY_IP` en
> `docs/PLAN_TRONCAL_ELASTIX.md` (en `external_media_address`).

---

## 7. Notas específicas de Mac (Apple Silicon)

- **Rendimiento del LLM:** excelente por Metal al ser nativo. STT (whisper) y TTS
  (Kokoro) van en CPU dentro del contenedor, sin problema para una llamada.
- **Imagen de Asterisk:** `andrius/asterisk:latest` puede no tener build arm64 y
  correr emulada por QEMU. Suele funcionar; si notaras latencia o inestabilidad
  en la señalización, avísame y buscamos una imagen arm64 nativa.
- **`host.docker.internal`** resuelve de forma nativa en Docker Desktop para Mac;
  no hay que añadir `extra_hosts`.
- Si Ollama se cae, los contenedores seguirán arriba pero el agente dará error de
  LLM hasta relanzar `ollama serve`.

---

## 8. Operación diaria (recordatorio de los dos `-f`)

| Acción | Comando |
|---|---|
| Arrancar | `docker compose -f docker-compose.yml -f docker-compose.mac.yml up -d` |
| Parar | `… stop` |
| Logs | `… logs -f audiosocket` |
| Reiniciar tras cambio Python | `… restart audiosocket webui` |
| Reconstruir UI | `… up -d --build webui` |

(Si exportaste `COMPOSE_FILE` como en §4, omite los `-f`.)
