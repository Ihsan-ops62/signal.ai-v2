import logging
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

class STTService:
    def __init__(self):
        logger.info("Loading Whisper STT model...")
        # "base.en" is fast. If you have a good GPU, you can change device="cuda"
        self.model = WhisperModel("base.en", device="cpu", compute_type="int8")
        logger.info("Whisper model loaded successfully.")

    def transcribe(self, audio_file_path: str) -> str:
        """Converts an audio file into text."""
        logger.info(f"Transcribing audio: {audio_file_path}")
        segments, info = self.model.transcribe(audio_file_path, beam_size=5)
        text = "".join([segment.text for segment in segments])
        return text.strip()

# Initialize a global instance so it only loads once
stt_service = STTService()