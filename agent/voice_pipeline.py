"""Pipeline de voz (Fase 2, paso 1: archivos) — plan.md §6.

Encadena STT (faster-whisper) -> agente (Fase 1, con tool calling) -> TTS (Kokoro)
y mide latencias. Trabaja con archivos WAV para ser determinista y medible, sin
depender todavía del micrófono (eso es el paso 2).

Uso (dentro del contenedor 'voice'):
    python -m agent.voice_pipeline --selftest
    python -m agent.voice_pipeline --say "hola, ¿en qué puedo ayudarte?" --wav-out /app/out.wav
    python -m agent.voice_pipeline --wav-in /app/pregunta.wav --wav-out /app/respuesta.wav
"""
from __future__ import annotations

import argparse
import sys
import time

from . import config


def _t() -> float:
    return time.perf_counter()


def selftest() -> int:
    """TTS -> STT de ida y vuelta: valida que ambos motores cargan y encajan."""
    from . import stt, tts

    frase = "Hola, soy el asistente telefónico. ¿En qué puedo ayudarte hoy?"
    print(f"[TTS] sintetizando: {frase!r}")
    t0 = _t()
    audio = tts.synth(frase)
    t_tts = _t() - t0
    dur = len(audio) / config.TTS_SAMPLE_RATE
    print(f"[TTS] {dur:.2f}s de audio en {t_tts:.2f}s  (RTF={t_tts/max(dur,1e-9):.2f})")

    # Resamplear 24k -> 16k para Whisper
    import soxr

    audio16 = soxr.resample(audio, config.TTS_SAMPLE_RATE, 16000)
    print("[STT] transcribiendo lo que acabamos de sintetizar...")
    t0 = _t()
    texto = stt.transcribe(audio16)
    t_stt = _t() - t0
    print(f"[STT] {t_stt:.2f}s -> {texto!r}")
    print("\nOK: TTS y STT funcionan y encajan.")
    return 0


def full_loop(wav_in: str, wav_out: str, *, verbose: bool = False) -> int:
    """WAV pregunta -> STT -> agente (tool calling) -> TTS -> WAV respuesta."""
    from . import stt, tts
    from .llm import new_messages, run_conversation

    print(f"[STT] transcribiendo {wav_in} ...")
    t0 = _t()
    user_text = stt.transcribe_wav(wav_in)
    t_stt = _t() - t0
    print(f"[STT] {t_stt:.2f}s -> {user_text!r}")

    print("[LLM] pensando (con herramientas)...")
    t0 = _t()
    _, respuesta = run_conversation(new_messages(user_text), verbose=verbose)
    t_llm = _t() - t0
    print(f"[LLM] {t_llm:.2f}s -> {respuesta!r}")

    print(f"[TTS] sintetizando respuesta -> {wav_out} ...")
    t0 = _t()
    tts.synth_to_wav(respuesta, wav_out)
    t_tts = _t() - t0
    print(f"[TTS] {t_tts:.2f}s")

    total = t_stt + t_llm + t_tts
    print(f"\n[LATENCIAS] STT={t_stt:.2f}s  LLM={t_llm:.2f}s  TTS={t_tts:.2f}s  TOTAL={total:.2f}s")
    return 0


def bench() -> int:
    """Mide carga (una vez) e inferencia EN CALIENTE (lo que importa en producción)."""
    import soxr

    from . import stt, tts
    from .llm import new_messages, run_conversation

    frases = [
        "Hola, gracias por llamar. ¿En qué puedo ayudarte?",
        "Tu factura cincuenta y tres mil trescientos ochenta está pendiente de pago.",
        "He creado un ticket con tu reporte. Te contactaremos pronto.",
    ]

    print("== CARGA (una sola vez al arrancar el servicio) ==")
    t0 = _t(); tts.synth("hola"); t_load_tts = _t() - t0
    print(f"  TTS (Kokoro) carga+warmup: {t_load_tts:.2f}s")
    t0 = _t(); stt.transcribe(soxr.resample(tts.synth("hola"), config.TTS_SAMPLE_RATE, 16000)); t_load_stt = _t() - t0
    print(f"  STT (Whisper) carga+warmup: {t_load_stt:.2f}s")

    print("\n== INFERENCIA EN CALIENTE (por frase) ==")
    tts_rtfs, stt_times = [], []
    for f in frases:
        t0 = _t(); audio = tts.synth(f); dt = _t() - t0
        dur = len(audio) / config.TTS_SAMPLE_RATE
        rtf = dt / max(dur, 1e-9)
        tts_rtfs.append(rtf)
        print(f"  [TTS] {dur:4.1f}s audio en {dt:5.2f}s  RTF={rtf:.2f}  | {f[:40]}...")
        a16 = soxr.resample(audio, config.TTS_SAMPLE_RATE, 16000)
        t0 = _t(); txt = stt.transcribe(a16); dt = _t() - t0
        stt_times.append(dt)
        print(f"  [STT] {dt:5.2f}s -> {txt[:50]!r}")

    print("\n== LOOP COMPLETO EN CALIENTE (STT -> LLM+tools -> TTS) ==")
    pregunta = "¿cuál es el estado de la factura 53380?"
    audio_q = tts.synth(pregunta)
    a16 = soxr.resample(audio_q, config.TTS_SAMPLE_RATE, 16000)
    t0 = _t(); user_text = stt.transcribe(a16); t_stt = _t() - t0
    t0 = _t(); _, resp = run_conversation(new_messages(user_text)); t_llm = _t() - t0
    t0 = _t(); _ = tts.synth(resp); t_tts = _t() - t0
    print(f"  pregunta transcrita: {user_text!r}")
    print(f"  respuesta: {resp[:80]!r}")
    print(f"  STT={t_stt:.2f}s  LLM={t_llm:.2f}s  TTS={t_tts:.2f}s  TOTAL={t_stt+t_llm+t_tts:.2f}s")
    print(f"  TTFA sin streaming (clásico) = LLM+TTS = {t_llm + t_tts:.2f}s")

    # --- A1: time-to-first-audio con streaming de LLM + TTS por frases ---
    print("\n== STREAMING: TIME-TO-FIRST-AUDIO / TTFA (A1) ==")
    from .llm import stream_reply
    msgs = new_messages(user_text)
    t0 = _t()
    ttfa = None
    frases = 0
    audio_total_s = 0.0
    for sent in stream_reply(msgs):
        audio = tts.synth(sent)
        if ttfa is None:
            ttfa = _t() - t0
        frases += 1
        audio_total_s += len(audio) / config.TTS_SAMPLE_RATE
    total_stream = _t() - t0
    if ttfa is None:
        print("  (el modelo no produjo texto final)")
    else:
        print(f"  TTFA (streaming) = {ttfa:.2f}s   frases={frases}  audio={audio_total_s:.1f}s  generación_total={total_stream:.2f}s")
        print(f"  >>> Criterio A1: TTFA < 2.0 s  =>  {'OK ✓' if ttfa < 2.0 else 'NO CUMPLE ✗'}")

    import statistics
    print(f"\n[RESUMEN] TTS RTF medio={statistics.mean(tts_rtfs):.2f}  STT medio={statistics.mean(stt_times):.2f}s")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Pipeline de voz (Fase 2).")
    p.add_argument("--selftest", action="store_true", help="TTS<->STT de ida y vuelta.")
    p.add_argument("--bench", action="store_true", help="Benchmark de latencias (carga vs caliente).")
    p.add_argument("--say", metavar="TEXTO", help="Solo TTS: sintetiza TEXTO a --wav-out.")
    p.add_argument("--wav-in", metavar="PATH", help="WAV de entrada para el loop completo.")
    p.add_argument("--wav-out", metavar="PATH", help="WAV de salida.")
    p.add_argument("--verbose", action="store_true", help="Mostrar tool_calls del agente.")
    args = p.parse_args()

    if args.selftest:
        return selftest()
    if args.bench:
        return bench()
    if args.say:
        from . import tts

        out = args.wav_out or "/app/tts_out.wav"
        t0 = _t()
        tts.synth_to_wav(args.say, out)
        print(f"[TTS] guardado en {out} ({_t()-t0:.2f}s)")
        return 0
    if args.wav_in:
        if not args.wav_out:
            p.error("--wav-in requiere --wav-out")
        return full_loop(args.wav_in, args.wav_out, verbose=args.verbose)

    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
