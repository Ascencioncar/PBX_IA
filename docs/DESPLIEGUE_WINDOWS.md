# Despliegue en Windows (entorno de laboratorio)

> Entorno objetivo: **Windows 10/11 + WSL2 + Docker Desktop (backend WSL2)** con
> GPU NVIDIA (en este equipo: RTX 3070 Ti, 8 GB). Ollama corre **en contenedor**
> usando la GPU. Es el entorno con el que se desarrolló y validó el proyecto.

---

## 1. Requisitos

- **Windows 10/11** con **WSL2** habilitado (Ubuntu recomendado).
- **Docker Desktop** con *WSL2 backend* activado.
- **GPU NVIDIA** + driver reciente (con soporte CUDA/WSL). Comprobar:
  ```bash
  docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
  ```
  Debe listar la GPU. Si falla, revisa el driver y que Docker Desktop tenga
  habilitado el uso de GPU.
- ~15 GB libres de disco (imágenes + modelos).

> **Nota del puerto 11434:** en este equipo el host ya ocupa el 11434 (otro
> proceso). Por eso el servicio `ollama` **no publica** ese puerto: los demás
> contenedores lo alcanzan por la red interna (`http://ollama:11434`). No hay que
> hacer nada; solo no esperes ver 11434 en `localhost`.

---

## 2. Configuración inicial

1. Clona/abre el proyecto y crea el `.env`:
   ```bash
   cp .env.example .env
   ```
2. Revisa el `.env` (valores ya pensados para este equipo):
   - `LLM_THINK=false` (clave: con qwen3 el razonamiento dispara la latencia).
   - `WHISPER_DEVICE=cpu`, parámetros de TTS/STT.
   - `TOOLS_BASE_URL=` vacío → las herramientas con `{base}` responden **simulado**
     hasta que conectes una API real (ver `docs/MANUAL_HERRAMIENTAS.md`).

---

## 3. Levantar la pila

```bash
docker compose up -d --build
```

Esto construye y arranca: `ollama`, `audiosocket`, `asterisk` y `webui`
(`agent`/`voice` son CLIs que se usan a demanda).

Descarga el modelo la primera vez (queda en un volumen persistente):

```bash
docker compose exec ollama ollama pull qwen3:8b
# opcional, smoke test rápido:
docker compose exec ollama ollama pull llama3.2:3b
```

---

## 4. Verificación

```bash
docker compose ps                      # todos "running"/"healthy"
docker compose logs -f audiosocket     # debe decir que escucha en 0.0.0.0:9000
```

- **Interfaz web:** abre <http://localhost:8000> (configura herramientas, prueba
  el chat y cambia el modelo). Si ves la versión vieja, recarga con **Ctrl+F5**.
- **Chat de prueba:** en la UI, pestaña *Chat*, escribe
  *«¿cuál es el estado de la factura 53380?»*.

---

## 5. Prueba de voz (softphone)

1. Softphone (p. ej. Zoiper) en Windows, registrado como:
   - Usuario/extensión: `1001`  ·  Contraseña: `pbxlab1001`
   - Servidor/dominio: `127.0.0.1` (puerto 5060)
2. Marca **`600`** → debes oír **eco** (valida audio sin IA).
3. Marca **`100`** → te atiende el **agente de IA**.

> `5060/UDP` y el rango RTP `10000-10030/UDP` ya están publicados en
> `docker-compose.yml`. El softphone y Asterisk ven `127.0.0.1` porque están en el
> mismo equipo (ver `pjsip.conf`). Para conectar un PBX externo (Elastix) hay que
> cambiar las direcciones anunciadas: ver `docs/PLAN_TRONCAL_ELASTIX.md`.

---

## 6. Operación diaria

| Acción | Comando |
|---|---|
| Arrancar | `docker compose up -d` |
| Parar | `docker compose stop` |
| Ver estado | `docker compose ps` |
| Logs de un servicio | `docker compose logs -f audiosocket` |
| Reiniciar tras cambiar código Python | `docker compose restart audiosocket webui` |
| Reconstruir la UI tras cambiar el front | `docker compose up -d --build webui` |
| Consola de Asterisk | `docker compose exec asterisk asterisk -rx "pjsip show endpoints"` |

> **Importante:** el código Python se monta por volumen → un cambio se aplica con
> `restart`. El **frontend React** se compila dentro de la imagen → tras tocarlo
> hay que **reconstruir** `webui` (`--build`).

---

## 7. Problemas comunes

| Síntoma | Causa | Solución |
|---|---|---|
| `ollama` no arranca / sin GPU | Driver o GPU no visible en Docker | Repite el test `nvidia-smi` de §1; revisa Docker Desktop |
| La UI no carga en `:8000` | `webui` caído o imagen sin build | `docker compose up -d --build webui`; mira `docker compose logs webui` |
| Cambios de la UI no se ven | Caché del navegador / falta build | **Ctrl+F5**; reconstruye `webui` |
| El agente tarda mucho | `think` activo o modelo pesado | `LLM_THINK=false`; usa `qwen3:8b`; ver `BENCHMARKS.md` |
| Marcar 100/600 no da audio | NAT/RTP | Ver notas de NAT en `pjsip.conf` y el plan de troncal |

---

## 8. Paso a producción (Mac)

Para mover el servicio a la Mac (Apple Silicon), Ollama va **nativo** (Docker en
Mac no expone la GPU). Sigue `docs/DESPLIEGUE_MAC.md`.
