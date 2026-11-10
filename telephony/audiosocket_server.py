"""Servidor AudioSocket — plan.md §7.4 (camino B) + mejoras MejorPBX área A.

Habla el protocolo AudioSocket de Asterisk y, por cada llamada, ejecuta el bucle
de voz: escucha al llamante (VAD) -> STT -> agente con tool calling -> TTS -> audio.

Mejoras aplicadas:
  A1  streaming de TTS por frases (menor time-to-first-audio, TTFA).
  A2  barge-in opcional (interrumpir al agente hablando) vía config.BARGE_IN.
  A3  recorte de historial (ventana deslizante) para latencia estable.
  A4  frase de respaldo si el LLM falla (no corta la llamada).
  A5  topes de turno/llamada + soporte DTMF (teclear números).
  A6  logging estructurado con call_id + métricas de latencia por etapa.

Protocolo (TCP): header 3 bytes = [tipo][longitud big-endian] + payload.
  0x00 TERMINATE | 0x01 UUID (16B) | 0x03 DTMF (1B) | 0x10 AUDIO (slin 8kHz) | 0xff ERROR
"""
from __future__ import annotations

import queue
import select
import socket
import socketserver
import struct
import threading
import time
import uuid as uuidlib

import numpy as np
import soxr
import webrtcvad

from agent import config, obs, settings, stt, tts
from agent.llm import run_conversation, stream_reply, trim_history
from agent.textnorm import is_farewell

log = obs.get_logger("audiosocket")

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
BARGE_SPEECH_MS = 240           # voz sostenida del llamante que interrumpe (A2)

GREETING = "Hola, gracias por llamar. Soy el asistente virtual. ¿En qué puedo ayudarte?"
FALLBACK_LINE = "Disculpa, tuve un problema procesando eso. ¿Puedes repetirlo, por favor?"
TIMEOUT_LINE = "Debo finalizar la llamada por ahora. Gracias por comunicarte. Hasta luego."


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
        obs.set_call_id(uuidlib.uuid4().hex[:8])  # provisional hasta recibir T_UUID
        vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        messages = [{"role": "system", "content": settings.system_prompt()}]
        call_deadline = time.monotonic() + config.MAX_CALL_SECONDS
        log.info(f"conexión desde {peer}")

        try:
            self._speak(sock, GREETING)
            while True:
                turn = self._listen(sock, vad, call_deadline)
                if turn is None:
                    break  # colgó
                kind, data = turn
                if kind == "timeout":
                    self._speak(sock, TIMEOUT_LINE)
                    self._hangup(sock)
                    break
                if kind == "dtmf":
                    text = f"El número que marqué es {data}."
                    log.info(f"usuario (DTMF): {data}")
                else:  # audio
                    with obs.stage(log, "stt"):
                        text = self._stt(data)
                    if not text:
                        continue
                    log.info(f"usuario: {text!r}")

                messages.append({"role": "user", "content": text})
                trim_history(messages)

                reply, interrupted = self._respond(sock, messages)
                log.info(f"agente: {reply!r}")

                if interrupted:
                    continue  # el llamante interrumpió: a escuchar de nuevo
                if is_farewell(text) or is_farewell(reply):
                    log.info("despedida detectada -> colgando")
                    self._hangup(sock)
                    break
        except (ConnectionError, OSError) as e:
            log.info(f"socket cerrado: {e}")
        log.info(f"fin {peer}")

    # --- Generar y hablar la respuesta (A1 streaming + A4 fallback) ---
    def _respond(self, sock: socket.socket, messages: list[dict]) -> tuple[str, bool]:
        try:
            if config.VOICE_STREAMING:
                sentences = stream_reply(messages)
                return self._speak_stream(sock, sentences)
            _, reply = run_conversation(messages, verbose=False)
            self._speak(sock, reply)
            return reply, False
        except (ConnectionError, OSError):
            raise  # socket caído: lo maneja handle()
        except Exception as e:  # A4: cualquier fallo del LLM/TTS no corta la llamada
            log.warning(f"fallo generando respuesta: {e!r}; uso frase de respaldo")
            try:
                self._speak(sock, FALLBACK_LINE)
            except (ConnectionError, OSError):
                raise
            return FALLBACK_LINE, False

    # --- Escucha con VAD hasta fin de turno; soporta DTMF y topes (A5) ---
    def _listen(self, sock: socket.socket, vad: webrtcvad.Vad, call_deadline: float):
        buf = bytearray()
        utter = bytearray()
        triggered = False
        silence_ms = 0
        speech_ms = 0
        dtmf = ""
        while True:
            if time.monotonic() > call_deadline:
                return ("timeout", None)
            msg = _read_message(sock)
            if msg is None:
                return None
            mtype, payload = msg
            if mtype in (T_TERMINATE, T_ERROR):
                return None
            if mtype == T_UUID:
                try:
                    obs.set_call_id(str(uuidlib.UUID(bytes=payload[:16]))[:8])
                except (ValueError, IndexError):
                    pass
                continue
            if mtype == T_DTMF:
                digit = payload.decode("ascii", "ignore")
                if digit == "#":          # fin de entrada por teclado
                    if dtmf:
                        return ("dtmf", dtmf)
                elif digit == "*":        # corrige: limpia lo tecleado
                    dtmf = ""
                elif digit.isdigit():
                    dtmf += digit
                continue
            if mtype != T_AUDIO:
                continue
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
                    if speech_ms >= config.MAX_UTTERANCE_MS:  # A5: turno demasiado largo
                        return ("audio", bytes(utter))
                elif triggered:
                    utter.extend(frame)
                    silence_ms += FRAME_MS
                    if silence_ms >= END_SILENCE_MS and speech_ms >= MIN_SPEECH_MS:
                        return ("audio", bytes(utter))

    # --- STT: bytes PCM 8k -> texto ---
    def _stt(self, pcm8k: bytes) -> str:
        audio = np.frombuffer(pcm8k, dtype="<i2").astype(np.float32) / 32768.0
        audio16 = soxr.resample(audio, SR, 16000)
        return stt.transcribe(audio16)

    def _pcm_from_text(self, text: str) -> bytes:
        audio24 = tts.synth(text)
        audio8 = soxr.resample(audio24, config.TTS_SAMPLE_RATE, SR)
        return np.clip(audio8 * 32768.0, -32768, 32767).astype("<i2").tobytes()

    def _send_pcm(self, sock: socket.socket, pcm: bytes, interrupt: threading.Event | None) -> bool:
        """Envía PCM en tramas a ritmo real. Devuelve True si se interrumpió (A2)."""
        for i in range(0, len(pcm), FRAME_BYTES):
            if interrupt is not None and interrupt.is_set():
                return True
            frame = pcm[i : i + FRAME_BYTES]
            if len(frame) < FRAME_BYTES:
                frame = frame + b"\x00" * (FRAME_BYTES - len(frame))
            sock.sendall(bytes([T_AUDIO]) + struct.pack(">H", len(frame)) + frame)
            time.sleep(FRAME_MS / 1000.0)
        return False

    # --- TTS clásico (no streaming): texto completo -> audio ---
    def _speak(self, sock: socket.socket, text: str) -> None:
        pcm = self._pcm_from_text(text)
        self._drain(sock)
        self._send_pcm(sock, pcm, None)

    # --- A1: streaming por frases con pre-síntesis (productor/consumidor) ---
    def _speak_stream(self, sock: socket.socket, sentences) -> tuple[str, bool]:
        pcm_q: queue.Queue = queue.Queue(maxsize=4)
        spoken: list[str] = []
        STOP = object()
        t_start = time.perf_counter()

        def producer():
            try:
                for sent in sentences:
                    if not sent:
                        continue
                    spoken.append(sent)
                    pcm_q.put(self._pcm_from_text(sent))
            except Exception as e:  # noqa: BLE001
                log.warning(f"productor TTS falló: {e!r}")
            finally:
                pcm_q.put(STOP)

        worker = threading.Thread(target=producer, daemon=True)
        worker.start()

        # Barge-in opcional (A2): hilo que vigila si el llamante habla encima.
        interrupt = threading.Event()
        stop_listen = threading.Event()
        listener = None
        if config.BARGE_IN:
            listener = threading.Thread(
                target=self._barge_listener,
                args=(sock, interrupt, stop_listen),
                daemon=True,
            )
            listener.start()
        else:
            self._drain(sock)

        first = True
        interrupted = False
        try:
            while True:
                pcm = pcm_q.get()
                if pcm is STOP:
                    break
                if first:
                    obs.metric(log, "ttfa", stage="ttfa",
                               seconds=round(time.perf_counter() - t_start, 3))
                    first = False
                if self._send_pcm(sock, pcm, interrupt if config.BARGE_IN else None):
                    interrupted = True
                    break
        finally:
            stop_listen.set()
            if listener is not None:
                listener.join(timeout=1)
            worker.join(timeout=5)
        return " ".join(spoken), interrupted

    # --- A2: escucha durante la reproducción; marca interrupción si hay voz ---
    def _barge_listener(self, sock: socket.socket, interrupt: threading.Event, stop: threading.Event) -> None:
        vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        buf = bytearray()
        speech_ms = 0
        while not stop.is_set():
            try:
                ready, _, _ = select.select([sock], [], [], 0.1)
            except OSError:
                return
            if not ready:
                continue
            msg = _read_message(sock)
            if msg is None:
                return
            mtype, payload = msg
            if mtype != T_AUDIO:
                continue
            buf.extend(payload)
            while len(buf) >= FRAME_BYTES:
                frame = bytes(buf[:FRAME_BYTES])
                del buf[:FRAME_BYTES]
                if vad.is_speech(frame, SR):
                    speech_ms += FRAME_MS
                    if speech_ms >= BARGE_SPEECH_MS:
                        log.info("barge-in: el llamante interrumpió")
                        interrupt.set()
                        return
                else:
                    speech_ms = max(0, speech_ms - FRAME_MS)

    # --- Colgar: deja sonar la cola y pide a Asterisk terminar la llamada ---
    def _hangup(self, sock: socket.socket) -> None:
        time.sleep(0.4)
        try:
            sock.sendall(bytes([T_TERMINATE]) + struct.pack(">H", 0))
        except OSError:
            pass

    # --- Vaciar lo que llegó mientras hablábamos (cuando no hay barge-in) ---
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
    log.info("precalentando modelos (STT + TTS)...")
    t0 = time.perf_counter()
    audio = tts.synth("hola")
    stt.transcribe(soxr.resample(audio, config.TTS_SAMPLE_RATE, 16000))
    log.info(f"listo en {time.perf_counter() - t0:.1f}s")


def main() -> None:
    host = "0.0.0.0"
    port = config.AUDIOSOCKET_PORT
    obs.setup()
    _prewarm()
    log.info(
        f"AudioSocket escuchando en {host}:{port} "
        f"(LLM={config.MODEL} en {config.OLLAMA_HOST}, streaming={config.VOICE_STREAMING}, "
        f"barge_in={config.BARGE_IN})"
    )
    with ThreadedServer((host, port), CallHandler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
