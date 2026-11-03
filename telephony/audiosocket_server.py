"""Servidor AudioSocket — plan.md §7.4 (camino B).

Habla el protocolo AudioSocket de Asterisk y, por cada llamada, ejecuta el bucle
de voz: escucha al llamante (VAD detecta fin de turno) -> STT -> agente con tool
calling -> TTS -> devuelve audio a la llamada.

Protocolo (TCP): header de 3 bytes = [1 byte tipo][2 bytes longitud big-endian] + payload.
  0x00 TERMINATE | 0x01 UUID (16B) | 0x03 DTMF (1B) | 0x10 AUDIO (slin16 8kHz mono LE) | 0xff ERROR

Audio de Asterisk: PCM 16-bit, 8 kHz, mono, little-endian. Reusamos:
  - STT (faster-whisper) a 16 kHz  -> resample 8k->16k
  - TTS (Kokoro) a 24 kHz          -> resample 24k->8k
"""
from __future__ import annotations

import socket
import socketserver
import struct
import threading
import time
import unicodedata

import numpy as np
import soxr
import webrtcvad

from agent import config, stt, tts
from agent.llm import SYSTEM_PROMPT, run_conversation

# --- Tipos de trama ---
T_TERMINATE = 0x00
T_UUID = 0x01
T_DTMF = 0x03
T_AUDIO = 0x10  # 8 kHz
T_ERROR = 0xFF

SR = 8000                       # Asterisk slin 8 kHz
FRAME_MS = 20
FRAME_SAMPLES = SR * FRAME_MS // 1000     # 160
FRAME_BYTES = FRAME_SAMPLES * 2           # 320

# Turnos (VAD)
VAD_AGGRESSIVENESS = 2
END_SILENCE_MS = 700            # silencio tras hablar => fin de turno
MIN_SPEECH_MS = 300             # mínimo de voz para considerar un turno

GREETING = "Hola, gracias por llamar. Soy el asistente virtual. ¿En qué puedo ayudarte?"

# Despedida: si el usuario (o el agente) se despide, colgamos tras responder.
_FAREWELL_HINTS = (
    "adios", "hasta luego", "hasta pronto", "hasta la proxima", "hasta la vista",
    "nos vemos", "chao", "chau", "me despido",
    "eso es todo", "eso seria todo", "con eso es todo",
    "nada mas gracias", "nada mas, gracias",
    "gracias eso es todo", "gracias, eso es todo",
    "que tengas buen dia", "que tenga buen dia",
    "que tengas un buen dia", "que tenga un buen dia",
)


def _normalize(text: str) -> str:
    """Minúsculas y sin acentos, para comparar de forma robusta."""
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _is_farewell(text: str) -> bool:
    t = _normalize(text)
    return any(h in t for h in _FAREWELL_HINTS)


def _recv_exact(sock: socket.socket, n: int) -> bytes | None:
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data.extend(chunk)
    return bytes(data)


def _read_message(sock: socket.socket) -> tuple[int, bytes] | None:
    header = _recv_exact(sock, 3)
    if header is None:
        return None
    mtype = header[0]
    (length,) = struct.unpack(">H", header[1:3])
    payload = _recv_exact(sock, length) if length else b""
    if payload is None:
        return None
    return mtype, payload


class CallHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        sock: socket.socket = self.request
        peer = self.client_address
        print(f"[call] conexión desde {peer}")
        vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        try:
            self._speak(sock, GREETING)
            while True:
                utter = self._listen(sock, vad)
                if utter is None:
                    break  # colgó
                text = self._stt(utter)
                if not text:
                    continue
                print(f"[call] usuario: {text!r}")
                messages.append({"role": "user", "content": text})
                _, reply = run_conversation(messages, verbose=False)
                print(f"[call] agente: {reply!r}")
                self._speak(sock, reply)
                # Si alguien se despidió, cerramos la llamada tras hablar.
                if _is_farewell(text) or _is_farewell(reply):
                    print("[call] despedida detectada -> colgando")
                    self._hangup(sock)
                    break
        except (ConnectionError, OSError) as e:
            print(f"[call] socket cerrado: {e}")
        print(f"[call] fin {peer}")

    # --- Escucha con VAD hasta el fin del turno ---
    def _listen(self, sock: socket.socket, vad: webrtcvad.Vad) -> bytes | None:
        buf = bytearray()
        utter = bytearray()
        triggered = False
        silence_ms = 0
        speech_ms = 0
        while True:
            msg = _read_message(sock)
            if msg is None:
                return None
            mtype, payload = msg
            if mtype in (T_TERMINATE, T_ERROR):
                return None
            if mtype != T_AUDIO:
                continue  # UUID/DTMF: ignorar por ahora
            buf.extend(payload)
            while len(buf) >= FRAME_BYTES:
                frame = bytes(buf[:FRAME_BYTES])
                del buf[:FRAME_BYTES]
                is_speech = vad.is_speech(frame, SR)
                if is_speech:
                    triggered = True
                    utter.extend(frame)
                    silence_ms = 0
                    speech_ms += FRAME_MS
                elif triggered:
                    utter.extend(frame)
                    silence_ms += FRAME_MS
                    if silence_ms >= END_SILENCE_MS and speech_ms >= MIN_SPEECH_MS:
                        return bytes(utter)

    # --- STT: bytes PCM 8k -> texto ---
    def _stt(self, pcm8k: bytes) -> str:
        audio = np.frombuffer(pcm8k, dtype="<i2").astype(np.float32) / 32768.0
        audio16 = soxr.resample(audio, SR, 16000)
        return stt.transcribe(audio16)

    # --- TTS: texto -> tramas de audio 8k hacia Asterisk ---
    def _speak(self, sock: socket.socket, text: str) -> None:
        audio24 = tts.synth(text)                      # float32 24 kHz
        audio8 = soxr.resample(audio24, config.TTS_SAMPLE_RATE, SR)
        pcm = np.clip(audio8 * 32768.0, -32768, 32767).astype("<i2").tobytes()

        self._drain(sock)  # descartar audio del llamante acumulado mientras no leíamos
        for i in range(0, len(pcm), FRAME_BYTES):
            frame = pcm[i : i + FRAME_BYTES]
            if len(frame) < FRAME_BYTES:
                frame = frame + b"\x00" * (FRAME_BYTES - len(frame))
            sock.sendall(bytes([T_AUDIO]) + struct.pack(">H", len(frame)) + frame)
            time.sleep(FRAME_MS / 1000.0)  # ritmo ~tiempo real

    # --- Colgar: deja sonar la cola y pide a Asterisk terminar la llamada ---
    def _hangup(self, sock: socket.socket) -> None:
        time.sleep(0.4)  # margen para que se reproduzca el final de la despedida
        try:
            sock.sendall(bytes([T_TERMINATE]) + struct.pack(">H", 0))
        except OSError:
            pass

    # --- Vaciar lo que llegó mientras hablábamos (sin barge-in en v1) ---
    def _drain(self, sock: socket.socket) -> None:
        sock.setblocking(False)
        try:
            while True:
                if not sock.recv(4096):
                    break
        except (BlockingIOError, OSError):
            pass
        finally:
            sock.setblocking(True)


class ThreadedServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _prewarm() -> None:
    """Carga STT y TTS antes de recibir llamadas (evita latencia en el 1er turno)."""
    print("[server] precalentando modelos (STT + TTS)...")
    t0 = time.perf_counter()
    audio = tts.synth("hola")
    stt.transcribe(soxr.resample(audio, config.TTS_SAMPLE_RATE, 16000))
    print(f"[server] listo en {time.perf_counter() - t0:.1f}s")


def main() -> None:
    host = "0.0.0.0"
    port = config.AUDIOSOCKET_PORT
    _prewarm()
    print(f"[server] AudioSocket escuchando en {host}:{port} (LLM={config.MODEL} en {config.OLLAMA_HOST})")
    with ThreadedServer((host, port), CallHandler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
