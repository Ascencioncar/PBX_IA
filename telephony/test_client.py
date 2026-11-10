"""Cliente de prueba del servidor AudioSocket (sin softphone).

Simula una llamada: manda la frase del "llamante" como audio 8 kHz por el
protocolo AudioSocket, espera el saludo, habla, y captura la respuesta del
agente; la transcribe para verificar que todo el loop funcionó.

Uso (en la red de compose):
    docker compose run --rm -T audiosocket python -m telephony.test_client \
        --text "¿cuál es el estado de la factura 53380?" --host audiosocket --port 9000
"""
from __future__ import annotations

import argparse
import socket
import struct
import uuid

import numpy as np
import soxr

from agent import config, stt, tts

T_UUID = 0x01
T_AUDIO = 0x10
SR = 8000
FRAME_BYTES = SR * 20 // 1000 * 2  # 320


def _frames_from_text(text: str) -> bytes:
    audio24 = tts.synth(text)
    audio8 = soxr.resample(audio24, config.TTS_SAMPLE_RATE, SR)
    return np.clip(audio8 * 32768.0, -32768, 32767).astype("<i2").tobytes()


def _send_audio(sock: socket.socket, pcm: bytes) -> None:
    for i in range(0, len(pcm), FRAME_BYTES):
        frame = pcm[i : i + FRAME_BYTES].ljust(FRAME_BYTES, b"\x00")
        sock.sendall(bytes([T_AUDIO]) + struct.pack(">H", len(frame)) + frame)


def _read_until_gap(sock: socket.socket, gap_s: float = 0.6, start_s: float = 8.0) -> bytes:
    """Lee tramas de audio hasta un silencio (gap). Espera hasta ``start_s`` a que empiece."""
    out = bytearray()
    first = True
    try:
        while True:
            sock.settimeout(start_s if first else gap_s)
            header = sock.recv(3)
            if len(header) < 3:
                break
            first = False
            mtype = header[0]
            (length,) = struct.unpack(">H", header[1:3])
            payload = b""
            while len(payload) < length:
                chunk = sock.recv(length - len(payload))
                if not chunk:
                    break
                payload += chunk
            if mtype == T_AUDIO:
                out.extend(payload)
    except TimeoutError:
        pass
    return bytes(out)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--text", default="¿cuál es el estado de la factura 53380?")
    p.add_argument("--host", default="audiosocket")
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--out", default="/app/respuesta_llamada.wav")
    args = p.parse_args()

    print(f"[client] sintetizando pregunta: {args.text!r}")
    pregunta = _frames_from_text(args.text)
    silencio = b"\x00" * (FRAME_BYTES * 50)  # ~1s de silencio => dispara fin de turno (VAD)

    print(f"[client] conectando a {args.host}:{args.port}")
    with socket.create_connection((args.host, args.port), timeout=10) as sock:
        sock.sendall(bytes([T_UUID]) + struct.pack(">H", 16) + uuid.uuid4().bytes)

        saludo = _read_until_gap(sock)
        print(f"[client] saludo recibido: {len(saludo)} bytes de audio (~{len(saludo)/2/SR:.1f}s)")

        print("[client] 'hablando' (enviando la pregunta)...")
        _send_audio(sock, pregunta + silencio)

        print("[client] esperando respuesta del agente (LLM+tools puede tardar ~10s)...")
        respuesta = _read_until_gap(sock, gap_s=3.0, start_s=30.0)
        print(f"[client] respuesta: {len(respuesta)} bytes (~{len(respuesta)/2/SR:.1f}s de audio)")

        # Verificación: transcribir lo que dijo el agente.
        if respuesta:
            audio = np.frombuffer(respuesta, dtype="<i2").astype(np.float32) / 32768.0
            audio16 = soxr.resample(audio, SR, 16000)
            texto = stt.transcribe(audio16)
            print(f"[client] el agente DIJO: {texto!r}")
            import soundfile as sf

            sf.write(args.out, soxr.resample(audio, SR, SR), SR)
            print(f"[client] audio guardado en {args.out}")
        else:
            print("[client] (sin respuesta de audio)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
