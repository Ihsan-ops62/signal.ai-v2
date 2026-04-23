from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import os
import random
import re
import tempfile
from typing import AsyncIterator, Optional

import edge_tts
from faster_whisper import WhisperModel

from agents.conversation.conversation_agent import ConversationAgent

logger = logging.getLogger(__name__)

# Configuration
_MIN_AUDIO_BYTES: int = 512
_MAX_TTS_CHARS: int = 1500

_WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL", "small")
_VAD_SILENCE_MS: int = 700

# Use a highly expressive neural voice – Aria is conversational, Jenny is warm.
_TTS_VOICE: str = os.getenv("TTS_VOICE", "en-US-AriaNeural")
_TTS_RATE: str = "-5%"      
_TTS_PITCH: str = "+0Hz"
_USE_SSML: bool = os.getenv("TTS_USE_SSML", "true").lower() == "true"

_ENABLE_AUDIO_PREPROCESS: bool = os.getenv("AUDIO_PREPROCESS", "true").lower() == "true"


# Fast JSON serialiser
try:
    import orjson
    def _dumps(obj: dict) -> str:
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj: dict) -> str:
        return json.dumps(obj)


# Event hierarchy 
class VoiceAgentEvent:
    __slots__ = ("type",)
    def __init__(self, type_: str) -> None:
        self.type = type_

class STTOutputEvent(VoiceAgentEvent):
    __slots__ = ("transcript",)
    def __init__(self, transcript: str) -> None:
        super().__init__("stt_output")
        self.transcript = transcript

class AgentChunkEvent(VoiceAgentEvent):
    __slots__ = ("text",)
    def __init__(self, text: str) -> None:
        super().__init__("agent_chunk")
        self.text = text

class TTSAudioEvent(VoiceAgentEvent):
    __slots__ = ("audio",)
    def __init__(self, audio: bytes) -> None:
        super().__init__("tts_audio")
        self.audio = audio

class TTSEndEvent(VoiceAgentEvent):
    __slots__ = ()
    def __init__(self) -> None:
        super().__init__("tts_end")

class ErrorEvent(VoiceAgentEvent):
    __slots__ = ("message",)
    def __init__(self, message: str) -> None:
        super().__init__("error")
        self.message = message


# Audio preprocessing 
async def _preprocess_audio(audio_bytes: bytes) -> bytes:
    if not _ENABLE_AUDIO_PREPROCESS:
        return audio_bytes
    try:
        from pydub import AudioSegment
        from pydub.effects import normalize, strip_silence
        def _process() -> bytes:
            seg = AudioSegment.from_file(io.BytesIO(audio_bytes))
            seg = seg.set_frame_rate(16_000).set_channels(1).set_sample_width(2)
            seg = normalize(seg)
            seg = strip_silence(seg, silence_thresh=-40, min_silence_len=200)
            out = io.BytesIO()
            seg.export(out, format="wav")
            return out.getvalue()
        return await asyncio.get_running_loop().run_in_executor(None, _process)
    except Exception as e:
        logger.debug("Audio preprocessing skipped: %s", e)
        return audio_bytes


# STT stage 
async def stt_stream(
    audio_stream: AsyncIterator[bytes],
    whisper_model: WhisperModel,
) -> AsyncIterator[VoiceAgentEvent]:
    buf = bytearray()
    async for chunk in audio_stream:
        if chunk:
            buf.extend(chunk)
    if len(buf) < _MIN_AUDIO_BYTES:
        yield ErrorEvent("No audio received — microphone might be silent.")
        return
    processed = await _preprocess_audio(bytes(buf))
    transcript = await _transcribe(processed, whisper_model)
    if not transcript:
        yield ErrorEvent("No speech detected in the audio.")
        return
    yield STTOutputEvent(transcript)


async def _transcribe(audio_bytes: bytes, model: WhisperModel) -> str:
    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
            fh.write(audio_bytes)
            tmp_path = fh.name
        loop = asyncio.get_running_loop()
        segments, info = await loop.run_in_executor(
            None,
            lambda: model.transcribe(
                tmp_path,
                language="en",
                beam_size=5,
                best_of=5,
                vad_filter=True,
                vad_parameters={
                    "min_silence_duration_ms": _VAD_SILENCE_MS,
                    "threshold": 0.4,
                },
                condition_on_previous_text=False,
            ),
        )
        transcript = " ".join(seg.text.strip() for seg in segments).strip()
        logger.debug("Whisper transcribed: %r", transcript[:100])
        return transcript
    except Exception as exc:
        logger.error("Whisper transcription failed: %s", exc)
        return ""
    finally:
        if tmp_path:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


# Agent stage
async def agent_stream(
    event_stream: AsyncIterator[VoiceAgentEvent],
    conversation_agent: ConversationAgent,
    session_id: str,
    voice_mode: bool = True,
) -> AsyncIterator[VoiceAgentEvent]:
    async for event in event_stream:
        yield event
        if not isinstance(event, STTOutputEvent):
            continue
        logger.info("[agent] transcript: %r", event.transcript[:100])
        try:
            response = await conversation_agent.chat(
                event.transcript,
                session_id=session_id,
                voice_mode=voice_mode,
            )
        except Exception as exc:
            logger.error("[agent] LLM error: %s", exc)
            yield ErrorEvent(f"LLM error: {exc}")
            continue
        if response:
            yield AgentChunkEvent(response)


# TTS stage with advanced SSML
async def tts_stream(
    event_stream: AsyncIterator[VoiceAgentEvent],
    voice: str = _TTS_VOICE,
    rate: str = _TTS_RATE,
    pitch: str = _TTS_PITCH,
    use_ssml: bool = _USE_SSML,
) -> AsyncIterator[VoiceAgentEvent]:
    async for event in event_stream:
        yield event
        if not isinstance(event, AgentChunkEvent):
            continue
        clean_text = _clean_for_speech(event.text)
        if not clean_text:
            continue
        async for tts_event in _synthesise(clean_text, voice, rate, pitch, use_ssml):
            yield tts_event
    yield TTSEndEvent()


def _clean_for_speech(text: str) -> str:
    """Remove emojis, hashtags, and markdown that TTS would mispronounce."""
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "]+", flags=re.UNICODE
    )
    text = emoji_pattern.sub("", text)
    text = re.sub(r"#(\w+)", r"\1", text)
    text = re.sub(r"[*_~`]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _text_to_ssml(text: str) -> str:
    """
    Convert plain text into expressive SSML with:
      - Pitch variation (random micro‑inflections)
      - Slower rate at sentence ends
      - Natural pause durations
      - Emphasis on adjectives and numbers
    """
    # Escape XML special characters
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Split into sentences (rough)
    sentences = re.split(r"(?<=[.!?])\s+", text)

    ssml_parts = []
    for i, sent in enumerate(sentences):
        if not sent.strip():
            continue

        # Process words within the sentence
        words = sent.split()
        processed_words = []
        for word in words:
            # Add pitch variation on longer words (simulate natural inflection)
            if len(word) > 5 and random.random() < 0.3:
                # Slight upward inflection
                word = f'<prosody pitch="+5%">{word}</prosody>'
            elif word.isdigit() or re.match(r"^\d+[.,]?\d*$", word):
                # Numbers stand out a bit
                word = f'<prosody pitch="+3%" rate="slow">{word}</prosody>'
            processed_words.append(word)

        sent = " ".join(processed_words)

        # Add a final slowing at the end of the sentence
        if i == len(sentences) - 1:
            # Last sentence: slow down slightly at the end
            sent = f'<prosody rate="slow">{sent}</prosody>'

        ssml_parts.append(sent)

    # Join sentences with appropriate breaks
    ssml_text = ""
    for i, sent in enumerate(ssml_parts):
        ssml_text += sent
        if i < len(ssml_parts) - 1:
            # Pause between sentences (500ms feels natural)
            ssml_text += '<break time="500ms"/> '

    # Add a short pause after the final sentence
    ssml_text += '<break time="200ms"/>'

    # Wrap in speak tag
    return f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">{ssml_text}</speak>'


async def _synthesise(
    text: str,
    voice: str,
    rate: str,
    pitch: str,
    use_ssml: bool,
) -> AsyncIterator[VoiceAgentEvent]:
    if not text:
        return
    if len(text) > _MAX_TTS_CHARS:
        text = text[:_MAX_TTS_CHARS]

    try:
        if use_ssml:
            ssml = _text_to_ssml(text)
            communicate = edge_tts.Communicate(
                ssml,
                voice=voice,
                # prosody tags override global rate/pitch, but we keep defaults
                rate=rate,
                pitch=pitch,
            )
        else:
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=rate,
                pitch=pitch,
            )
        async for chunk in communicate.stream():
            if chunk["type"] == "audio" and chunk.get("data"):
                yield TTSAudioEvent(chunk["data"])
    except Exception as exc:
        logger.error("[tts] synthesis failed: %s", exc)
        yield ErrorEvent(f"TTS error: {exc}")


#  WebSocket session 
class VoicePipelineSession:
    def __init__(
        self,
        websocket,
        whisper_model: WhisperModel,
        conversation_agent: ConversationAgent,
        session_id: str,
        voice_mode: bool = True,
    ) -> None:
        self.ws = websocket
        self.whisper = whisper_model
        self.agent = conversation_agent
        self.session_id = session_id
        self.voice_mode = voice_mode
        self._interrupted = asyncio.Event()
        self._current_task: Optional[asyncio.Task] = None

    async def run(self) -> None:
        audio_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=256)

        async def _ws_producer() -> None:
            try:
                while True:
                    msg = await self.ws.receive()
                    if "bytes" in msg:
                        await audio_queue.put(msg["bytes"])
                    elif "text" in msg:
                        data = json.loads(msg["text"])
                        if data.get("type") == "interrupt":
                            self._interrupted.set()
                            if self._current_task and not self._current_task.done():
                                self._current_task.cancel()
                        elif data.get("type") == "utterance_end":
                            await audio_queue.put(None)
                            break
            except Exception:
                await audio_queue.put(None)

        async def _audio_source() -> AsyncIterator[bytes]:
            while True:
                chunk = await audio_queue.get()
                if chunk is None:
                    break
                yield chunk

        producer_task = asyncio.create_task(_ws_producer())

        try:
            pipeline = stt_stream(_audio_source(), self.whisper)
            pipeline = agent_stream(pipeline, self.agent, self.session_id, self.voice_mode)
            pipeline = tts_stream(pipeline)

            self._interrupted.clear()
            self._current_task = asyncio.current_task()

            async for event in pipeline:
                if self._interrupted.is_set():
                    break
                if isinstance(event, TTSAudioEvent):
                    await self.ws.send_bytes(event.audio)
                elif isinstance(event, STTOutputEvent):
                    await self._send({"type": "transcript", "text": event.transcript})
                elif isinstance(event, AgentChunkEvent):
                    await self._send({"type": "response_text", "text": event.text})
                elif isinstance(event, TTSEndEvent):
                    await self._send({"type": "tts_end"})
                elif isinstance(event, ErrorEvent):
                    await self._send({"type": "error", "message": event.message})

        except asyncio.CancelledError:
            logger.info("[voice] pipeline cancelled — session %s", self.session_id)
        except Exception as exc:
            logger.error("[voice] pipeline error: %s", exc)
            await self._send({"type": "error", "message": str(exc)})
        finally:
            self._current_task = None
            producer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await producer_task

    async def _send(self, payload: dict) -> None:
        try:
            await self.ws.send_text(_dumps(payload))
        except Exception as exc:
            logger.debug("[voice] send failed: %s", exc)