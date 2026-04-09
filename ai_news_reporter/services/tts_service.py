import logging
import edge_tts

logger = logging.getLogger(__name__)

class TTSService:
    @staticmethod
    async def generate_audio(text: str, output_filepath: str) -> str:
        """Converts text to an audio file and saves it."""
        logger.info("Generating TTS audio...")
        # "en-US-ChristopherNeural" is a professional-sounding male voice. 
        # You can also try "en-US-AriaNeural" for a female voice.
        communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural")
        await communicate.save(output_filepath)
        return output_filepath