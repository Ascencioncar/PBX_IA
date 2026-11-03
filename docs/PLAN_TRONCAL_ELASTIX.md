# Plan: troncal SIP desde Elastix hacia el servicio de IA

> Objetivo: que un PBX **Elastix** en producción pueda enviar una llamada a un
> **número específico** (p. ej. `7000`) y que esa llamada la atienda nuestro
> **agente de voz con IA** (STT → LLM con herramientas → TTS).
>
> Fecha: 2026-11-02 · Aplica a la pila dockerizada de este repo.

---

## 1. Arquitectura

Elastix **no** habla AudioSocket. La integración se hace con una **troncal SIP**
entre Elastix y nuestro Asterisk (el "gateway de IA"), que es quien sí corre
AudioSocket y puentea al orquestador Python.

```
  Llamante                 ELASTIX (producción)            GATEWAY DE IA (este repo)
 ┌────────┐   ext/DID    ┌──────────────────────┐  SIP   ┌────────────────────────────┐
 │ teléfono│ ───────────▶│  marca 7000 / DID     │ troncal│ Asterisk  context=from-elastix│
 └────────┘             │  → Ruta → Troncal ai  │───────▶│   exten 7000 → AudioSocket     │
                         └──────────────────────┘ 5060/  └───────────────┬────────────────┘
                                                   RTP                    │ TCP :9000 (AudioSocket)
                                                                          ▼
                                                        ┌────────────────────────────────┐
                                                        │ audiosocket (Python)            │
                                                        │  VAD → STT(whisper) → LLM(tools) │
                                                        │       → TTS(Kokoro) → audio      │
                                                        └────────────────────────────────┘
```

- **Transporte entre PBX:** SIP/UDP 5060 + RTP (G.711 ulaw/alaw).
- **Autenticación de la troncal:** por **IP** (`identify`), sin registro.
- **Dentro de nuestra pila:** Asterisk → `audiosocket:9000` por la red interna de
  Docker (sin cambios respecto a lo que ya funciona con el softphone).

### Variables que usarás

| Nombre | Qué es | Ejemplo |
|---|---|---|
| `ELASTIX_IP` | IP del PBX Elastix en la LAN | `192.168.1.10` |
| `GATEWAY_IP` | IP del **host** que corre Docker (Windows hoy, Mac mañana) | `192.168.1.50` |
| `NUM_AGENTE` | Número específico que atiende la IA | `7000` |

> Averigua `GATEWAY_IP`: en Windows `ipconfig`, en Mac `ipconfig getifaddr en0`.
> Elastix y el gateway deben estar en la **misma LAN** (o unidos por VPN).

---

## 2. Requisitos previos

1. La pila de este repo levantada y el agente funcionando (ya validado con el
   softphone marcando `100`).
2. Conectividad IP entre Elastix y el gateway. Puertos abiertos **del gateway
   hacia/desde Elastix**:
   - `5060/UDP` (señalización SIP)
   - `10000-10030/UDP` (RTP — ya publicados en `docker-compose.yml`)
3. Decidir `NUM_AGENTE` (aquí `7000`).

---

## 3. Configuración del lado GATEWAY (este repo)

### 3.1 Transporte: anunciar la IP correcta (clave para el audio)

Con el softphone local usábamos `127.0.0.1`. Una troncal viene de **otra
máquina**, así que Asterisk debe anunciar en el SDP la IP del host Docker
(`GATEWAY_IP`); si no, habrá **audio en un solo sentido o mudo**.

Edita `telephony/asterisk/pjsip.conf`, bloque `[transport-udp]`:

```ini
[transport-udp]
type=transport
protocol=udp
bind=0.0.0.0:5060
external_media_address=GATEWAY_IP        ; p.ej. 192.168.1.50
external_signaling_address=GATEWAY_IP
local_net=172.16.0.0/12                  ; red interna de Docker = "local"
```

> Si quieres seguir probando el softphone local, ahora apúntalo también a
> `GATEWAY_IP` (no a `127.0.0.1`), para que todos vean la misma dirección.

### 3.2 Endpoint de la troncal + dialplan

Añade los bloques de los ejemplos ya incluidos en el repo:

- `telephony/asterisk/pjsip_trunk.conf.example` → al final de `pjsip.conf`
  (define `[elastix-trunk]`: endpoint, aor, identify por IP).
- `telephony/asterisk/extensions_trunk.conf.example` → al final de
  `extensions.conf` (define el contexto `[from-elastix]` que manda `7000` a
  AudioSocket).

Reemplaza `ELASTIX_IP` / `GATEWAY_IP` / `7000` por tus valores.

### 3.3 Recargar

```bash
docker compose exec asterisk asterisk -rx "pjsip reload"
docker compose exec asterisk asterisk -rx "dialplan reload"
# Si cambiaste el transporte (3.1), reinicia el contenedor (el transporte no recarga en caliente):
docker compose restart asterisk
```

Verifica:

```bash
docker compose exec asterisk asterisk -rx "pjsip show endpoints"      # debe salir elastix-trunk
docker compose exec asterisk asterisk -rx "pjsip show identifies"     # match = ELASTIX_IP
docker compose exec asterisk asterisk -rx "dialplan show from-elastix"
```

---

## 4. Configuración del lado ELASTIX

Elastix = FreePBX sobre Asterisk. Según la versión usa **chan_sip** (lo más común
en Elastix clásico) o **PJSIP** (FreePBX 15/16). Abajo ambos.

### 4.1 Crear la troncal — opción chan_sip (clásica)

**Connectivity → Trunks → Add SIP (chan_sip) Trunk**

- *Trunk Name:* `ai-agent`
- *Outbound CallerID:* el que quieras mostrar (opcional)
- **PEER Details:**

```ini
host=GATEWAY_IP
port=5060
type=peer
context=from-trunk
disallow=all
allow=ulaw&alaw
qualify=yes
insecure=port,invite
dtmfmode=rfc2833
```

> No se pone `register =>` : es una troncal **saliente** (Elastix inicia la
> llamada hacia el gateway). `qualify=yes` vigila el enlace.

### 4.2 Crear la troncal — opción PJSIP (FreePBX 15/16)

**Connectivity → Trunks → Add SIP (chan_pjsip) Trunk**

- Pestaña *General* → *Trunk Name:* `ai-agent`
- Pestaña *pjsip Settings → General:*
  - *Username:* `ai-agent`
  - *Authentication:* `None`   ·   *Registration:* `None`
  - *SIP Server:* `GATEWAY_IP`   ·   *SIP Server Port:* `5060`
- Pestaña *pjsip Settings → Advanced:*
  - *Context:* `from-trunk`
  - *Codecs:* `ulaw`, `alaw` (desactiva el resto)
  - *Direct Media:* `No`   ·   *RTP Symmetric:* `Yes`

### 4.3 Enrutar el "número específico" hacia la troncal

Tienes dos escenarios; elige el que aplique.

**A) Lo marcan usuarios internos (una extensión marca `7000` y cae en la IA)**

**Connectivity → Outbound Routes → Add Route**
- *Route Name:* `ia-agent`
- *Trunk Sequence:* `ai-agent`
- *Dial Patterns:* en la columna **match pattern** pon `7000`
  (deja prefijo/prepend vacíos: queremos enviar `7000` tal cual al gateway).

Resultado: cualquier extensión que marque `7000` sale por la troncal; el gateway
recibe `EXTEN=7000` y lo manda a AudioSocket.

**B) Entra por un DID del exterior (un número público va directo a la IA)**

**Connectivity → Inbound Routes → Add Inbound Route**
- *DID Number:* el DID que te da el operador
- *Set Destination:* una **Custom Destination** que empuje la llamada por la
  troncal. Crea antes en **Admin → Custom Destinations**:
  - *Target:* `from-trunk-ai,7000,1` (ver 4.4) · *Description:* `Agente IA`
  - y en `extensions_custom.conf` de Elastix:
    ```ini
    [from-trunk-ai]
    exten => 7000,1,Dial(SIP/ai-agent/7000)   ; chan_sip
    ; exten => 7000,1,Dial(PJSIP/7000@ai-agent) ; si la troncal es PJSIP
     same => n,Hangup()
    ```
  Apunta el *Inbound Route* a esa Custom Destination.

### 4.4 Aplicar en Elastix

Pulsa **Apply Config** (barra naranja de FreePBX). Si editaste
`extensions_custom.conf` a mano: **Admin → desde consola** `fwconsole reload`.

---

## 5. Prueba de extremo a extremo

1. Desde una extensión de Elastix, marca **`7000`**.
2. Debes oír el saludo del agente: *"Hola, gracias por llamar. Soy el asistente
   virtual…"* y poder conversar.

Observa en vivo en el gateway:

```bash
# Logs del orquestador (STT/LLM/TTS por llamada):
docker compose logs -f audiosocket

# Señalización SIP en Asterisk:
docker compose exec asterisk asterisk -rx "pjsip set logger on"
docker compose exec asterisk asterisk -rx "core show channels"
```

---

## 6. Solución de problemas

| Síntoma | Causa probable | Qué revisar |
|---|---|---|
| Elastix da **congestión** al marcar `7000` | Ruta/patrón no coincide o troncal caída | Outbound Route `7000`; `pjsip show identifies` en gateway; `qualify` OK |
| **401/403 / "forbidden"** en el gateway | La IP de Elastix no coincide con `identify` | `match=ELASTIX_IP` correcto; que Elastix salga por esa IP |
| **488 Not Acceptable Here** | Códecs incompatibles | Deja solo `ulaw`/`alaw` en ambos lados |
| Llamada conecta pero **audio mudo / en un sentido** | NAT: SDP anuncia IP equivocada | `external_media_address=GATEWAY_IP` (§3.1) + reinicio de `asterisk`; RTP `10000-10030/UDP` abierto entre ambos |
| Conecta y **cuelga a los ~2 s** sin saludo | No llega al servidor AudioSocket | `docker compose logs audiosocket`; que resuelva `audiosocket:9000` en la red Docker |
| Saludo entrecortado / latencia alta | Recursos del LLM/TTS | Revisa `BENCHMARKS.md`; `think` apagado; modelo adecuado |
| DTMF no se detecta | Modo DTMF distinto | `rfc2833` (Elastix) ↔ `rfc4733` (gateway) son compatibles; verifica ambos |

---

## 7. Producción y escalado (notas)

- **Concurrencia / RTP:** `10000-10030` = ~15 llamadas simultáneas. Amplía el
  rango en `rtp.conf` **y** el mapeo de puertos en `docker-compose.yml` si
  necesitas más. Cada llamada ocupa además una instancia del pipeline de voz
  (CPU para STT/TTS) y una petición al LLM.
- **Seguridad:** la troncal va por IP. Mantén 5060/RTP **solo** accesibles desde
  la IP de Elastix (firewall / red privada / VPN). No expongas 5060 a Internet.
- **Alta disponibilidad del número:** si `7000` debe tener plan B cuando la IA no
  responda, añade en Elastix un *failover* en la ruta (otra troncal/extensión).
- **Un número por flujo:** puedes mapear varios números a distintos saludos/
  comportamientos creando más `exten =>` en `[from-elastix]` y variando el
  prompt/herramientas del agente por contexto (mejora futura).

---

## 8. Checklist rápido

- [ ] `GATEWAY_IP` fijado en `[transport-udp]` (`external_media_address` /
      `external_signaling_address`) y `asterisk` reiniciado.
- [ ] `pjsip_trunk.conf.example` y `extensions_trunk.conf.example` aplicados y
      recargados; `pjsip show endpoints` muestra `elastix-trunk`.
- [ ] Puertos `5060/UDP` + `10000-10030/UDP` abiertos entre Elastix y gateway.
- [ ] Troncal `ai-agent` creada en Elastix apuntando a `GATEWAY_IP:5060`,
      códecs `ulaw/alaw`.
- [ ] Ruta que envía `7000` (o el DID) por la troncal `ai-agent`.
- [ ] **Apply Config** en Elastix.
- [ ] Prueba: marcar `7000` → se oye y conversa con el agente.
