"""
Gözde Plastik - Müşteri Hatırlatma Botu v2.2
Yapılandırma (.env'den okur)
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")


def _get_list(env_key: str, default: list = None) -> list:
    val = os.getenv(env_key, "")
    if not val:
        return default or []
    return [int(x.strip()) for x in val.split(",") if x.strip().isdigit()]


def _get_bool(env_key: str, default: bool = False) -> bool:
    val = os.getenv(env_key, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "y", "evet", "e", "on")


# ============================================================
# TELEGRAM
# ============================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
AUTHORIZED_CHAT_IDS = _get_list("AUTHORIZED_CHAT_IDS")

# ============================================================
# WHISPER
# ============================================================
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = "auto"
WHISPER_COMPUTE_TYPE = "int8"
WHISPER_LANGUAGE = "tr"
WHISPER_VAD_MIN_SILENCE_MS = 300

# ============================================================
# OLLAMA
# ============================================================
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT_SECONDS = 30  # v2.2: timeout

# ============================================================
# HAIKU - OPSİYONEL (v2.2)
# Varsayılan: kapalı. Açmak için .env'de USE_HAIKU=true
# ============================================================
USE_HAIKU = _get_bool("USE_HAIKU", False)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
HAIKU_MODEL = os.getenv("HAIKU_MODEL", "claude-haiku-4-5")
HAIKU_USE_FOR_RISK_ANALYSIS = _get_bool("HAIKU_USE_FOR_RISK_ANALYSIS", True)
HAIKU_USE_FOR_AMBIGUITY = _get_bool("HAIKU_USE_FOR_AMBIGUITY", False)

# ============================================================
# DOSYA YOLLARI
# ============================================================
DB_PATH = BASE_DIR / "reminders.db"
AUDIO_DIR = BASE_DIR / "audio"
AUDIO_DIR.mkdir(exist_ok=True)
AUDIO_ARCHIVE_DIR = BASE_DIR / "audio_archive"
AUDIO_ARCHIVE_DIR.mkdir(exist_ok=True)
IMPORT_DIR = BASE_DIR / "import"
IMPORT_DIR.mkdir(exist_ok=True)
BACKUP_DIR = BASE_DIR / "backups"
BACKUP_DIR.mkdir(exist_ok=True)
AUDIO_ARCHIVE_DAYS = 30

# ============================================================
# HATIRLATMA
# ============================================================
DEFAULT_REMINDER_HOURS_BEFORE = 24
DEFAULT_REMINDER_HOUR = 9
DEFAULT_REMINDER_MINUTE = 0
TIMEZONE = "Europe/Istanbul"

# ============================================================
# ESKALASYON
# ============================================================
ESCALATION_HOURS_AFTER_FIRST = 2
ESCALATION_NEXT_MORNING_HOUR = 9
MAX_ESCALATIONS = 3

# ============================================================
# RAPORLAR
# ============================================================
DAILY_BRIEF_ENABLED = True
DAILY_BRIEF_HOUR = 8
DAILY_BRIEF_MINUTE = 30
EVENING_RECAP_ENABLED = True
EVENING_RECAP_HOUR = 19
EVENING_RECAP_MINUTE = 0

# ============================================================
# iPhone REMINDERS
# ============================================================
APPLE_REMINDERS_ENABLED = True
APPLE_REMINDERS_CLI = os.getenv("APPLE_REMINDERS_CLI", "/opt/homebrew/bin/reminders")
APPLE_REMINDERS_LIST = "Gözde Plastik"
APPLE_REMINDERS_SYNC_INTERVAL_MIN = 5
APPLE_USE_APPLESCRIPT_FALLBACK = True

# ============================================================
# MÜŞTERİ
# ============================================================
RISK_LOW_THRESHOLD = 20
RISK_HIGH_THRESHOLD = 50
CUSTOMER_FUZZY_THRESHOLD = 0.75
CUSTOMER_AMBIGUITY_THRESHOLD = 0.10

# ============================================================
# KONUŞMA AKIŞI
# ============================================================
CONVERSATION_TIMEOUT_MIN = 30

# ============================================================
# AKILLI BAĞLAM
# ============================================================
SMART_WARNING_RISK_THRESHOLD = 40

# ============================================================
# SESLİ YANIT
# ============================================================
TTS_ENABLED = False
TTS_VOICE = "Yelda"

# ============================================================
# v2.2 YENİ AYARLAR
# ============================================================
# Duplicate ses kontrolü
DUPLICATE_VOICE_WINDOW_MIN = 5

# Telegram mesaj uzunluk limiti (4096 - pay)
TELEGRAM_MAX_MESSAGE_LENGTH = 4000

# Hafta sonu/bayram otomatik erteleme
SKIP_WEEKENDS = _get_bool("SKIP_WEEKENDS", False)
SKIP_TURKEY_HOLIDAYS = _get_bool("SKIP_TURKEY_HOLIDAYS", False)

# Türkiye 2026 resmi tatilleri
TURKEY_HOLIDAYS_2026 = [
    "2026-01-01",
    "2026-04-23",
    "2026-05-01",
    "2026-05-19",
    "2026-07-15",
    "2026-08-30",
    "2026-10-29",
    "2026-03-20", "2026-03-21", "2026-03-22",
    "2026-05-27", "2026-05-28", "2026-05-29", "2026-05-30",
]

# ============================================================
# LOG
# ============================================================
LOG_LEVEL = "INFO"
LOG_FILE = BASE_DIR / "bot.log"


# ============================================================
# BAŞLANGIÇ DOĞRULAMASI (v2.2)
# ============================================================

def validate() -> list:
    """Yapılandırmayı doğrula. Hata + uyarı listesi döner."""
    errors = []
    warnings = []

    if not TELEGRAM_BOT_TOKEN:
        errors.append(
            "TELEGRAM_BOT_TOKEN ayarlanmamis!\n"
            "  Cozum: .env dosyasini olustur (cp .env.example .env)\n"
            "  ve BotFather'dan aldigin token'i yaz."
        )

    if not AUTHORIZED_CHAT_IDS:
        warnings.append(
            "AUTHORIZED_CHAT_IDS bos! Herkes bota erisebilir.\n"
            "  Cozum: .env'de kendi Chat ID'ini yaz."
        )

    if USE_HAIKU:
        if not ANTHROPIC_API_KEY:
            errors.append(
                "USE_HAIKU=true ama ANTHROPIC_API_KEY yok!\n"
                "  Cozum: ya USE_HAIKU'yu false yap, ya da\n"
                "  console.anthropic.com'dan API key al."
            )

    for d in [AUDIO_DIR, AUDIO_ARCHIVE_DIR, IMPORT_DIR, BACKUP_DIR]:
        if not os.access(d, os.W_OK):
            errors.append(f"Yazma izni yok: {d}")

    valid_models = {"tiny", "base", "small", "medium", "large-v2", "large-v3"}
    if WHISPER_MODEL not in valid_models:
        warnings.append(f"Whisper modeli garip: {WHISPER_MODEL}")

    return [("HATA", e) for e in errors] + [("UYARI", w) for w in warnings]


def print_validation_and_exit_if_errors():
    """Doğrula, hata varsa çık"""
    issues = validate()
    has_errors = any(level == "HATA" for level, _ in issues)

    if issues:
        print("\n" + "=" * 60)
        print("  YAPILANDIRMA KONTROLU")
        print("=" * 60)
        for level, msg in issues:
            symbol = "[X]" if level == "HATA" else "[!]"
            print(f"\n{symbol} {msg}")
        print("\n" + "=" * 60 + "\n")

    if has_errors:
        print("Bot baslatilamiyor. Yukaridaki hatalari duzelt.\n")
        sys.exit(1)
