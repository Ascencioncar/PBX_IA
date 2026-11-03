# Benchmarks — Fase 2 (voz local)

Equipo: Ryzen 7 5800XT (8c/16t), 32 GB RAM, RTX 3070 Ti 8 GB. Windows 10 + WSL2 + Docker.
Medido con `docker compose run --rm voice python -m agent.voice_pipeline --bench`.

- **LLM**: `qwen3:8b` en Ollama (contenedor, GPU ~82%), `num_ctx=8192`, `num_predict=200`.
- **STT**: faster-whisper `small`, **CPU**, `int8` (para no pelear VRAM con el LLM).
- **TTS**: Kokoro-82M, **CPU**, voz `ef_dora` (español), 24 kHz.

## Carga (una sola vez al arrancar el servicio)

| Componente | Tiempo |
|---|---|
| TTS (Kokoro) carga+warmup | ~8.0 s |
| STT (Whisper) carga+warmup | ~3.4 s |

## Inferencia en caliente (lo que importa en producción)

| Etapa | Latencia | Nota |
|---|---|---|
| **TTS (Kokoro)** | **RTF ≈ 0.35** (p. ej. 3 s de audio en ~1 s) | 🟢 ~3× más rápido que tiempo real, en CPU |
| **STT (Whisper small/int8 CPU)** | **~2.1 s / frase** | 🟡 coste casi fijo |
| **LLM (loop con tools)** | **~7.4 s** | 2 llamadas (decidir tool + redactar) |
| **Loop completo** (STT→LLM+tools→TTS) | **~14 s** total | respuesta hablada completa |

## Hallazgo clave: apagar el "thinking" de qwen3

`qwen3` razona (`<think>…`) por defecto, lo que disparaba el LLM a **~51 s**. Con
`think=False` (ver `LLM_THINK` en `.env`) bajó a **~7.4 s**. Imprescindible para voz.

## Roadmap de optimización (perceived latency)

El total de 14 s es de la respuesta COMPLETA. Lo que percibe el llamante es
*tiempo hasta el primer audio*, mucho menor si hacemos **streaming por frases**:

1. **Streaming TTS por frase**: reproducir la 1.ª frase mientras se genera el resto
   (Kokoro RTF 0.35 ⇒ primer audio en ~0.5 s). Mayor ganancia percibida.
2. **Stream del LLM**: emitir tokens y cortar por frase para alimentar al TTS.
3. **VRAM**: cerrar apps que usan GPU y/o bajar `NUM_CTX` a 4096 para meter el LLM
   100 % en GPU (ahora ~18 % en CPU).
4. **STT en GPU** si queda VRAM (`WHISPER_DEVICE=cuda`), o `small`→`base` si urge latencia.
5. Números mal oídos por Whisper (p. ej. "53380"→"53.380"): probar `medium` o
   post-proceso; el LLM los normaliza bastante bien igualmente.
