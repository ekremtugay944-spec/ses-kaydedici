"""
macOS 'say' komutu ile sesli yanıt
İsteğe bağlı - config'de TTS_ENABLED ayarı
"""
import subprocess
import logging
from pathlib import Path
from config import TTS_ENABLED, TTS_VOICE, AUDIO_DIR

logger = logging.getLogger(__name__)


def is_enabled() -> bool:
    return TTS_ENABLED


def speak_to_file(text: str, output_path: Path) -> bool:
    """
    Metni sese çevir, dosyaya yaz.
    Mac'in 'say' komutunu kullanır (Türkçe için Yelda sesi önerilir).
    """
    if not TTS_ENABLED:
        return False
    try:
        # AIFF olarak kaydet, sonra ffmpeg ile m4a'ya çevir
        aiff_path = output_path.with_suffix(".aiff")
        subprocess.run(
            ["say", "-v", TTS_VOICE, "-o", str(aiff_path), text],
            capture_output=True, timeout=30, check=True,
        )
        # m4a'ya çevir (Telegram daha iyi destekler)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(aiff_path), "-codec:a", "aac",
             "-b:a", "64k", str(output_path)],
            capture_output=True, timeout=30, check=True,
        )
        aiff_path.unlink(missing_ok=True)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"TTS hatası: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"TTS exception: {e}")
        return False
    return False
