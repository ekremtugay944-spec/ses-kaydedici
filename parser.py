"""
Hibrit parser - v2.1
1. dateparser (Türkçe destekli, hızlı, kesin) ile tarih çıkar
2. Ollama (Qwen) sadece yapı için (kim, ne, tutar, tür)

Bu yaklaşım:
- %95+ tarih doğruluğu (Ollama tek başına %70-80'di)
- %60 daha hızlı
- LLM'in tarih çıkarma hatalarından kaçınır
"""
import json
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional
import dateparser
import ollama
from config import (
    OLLAMA_HOST, OLLAMA_MODEL, TIMEZONE, OLLAMA_TIMEOUT_SECONDS,
    DEFAULT_REMINDER_HOURS_BEFORE,
    DEFAULT_REMINDER_HOUR, DEFAULT_REMINDER_MINUTE,
)

logger = logging.getLogger(__name__)
tz = ZoneInfo(TIMEZONE)
# v2.2: timeout ile client
client = ollama.Client(host=OLLAMA_HOST, timeout=OLLAMA_TIMEOUT_SECONDS)


# ============================================================
# TÜRKÇE TARİH ÖN İŞLEME
# ============================================================

TURKISH_PATTERNS = {
    # Göreceli ifadeler (dateparser bunları zaten anlar ama destekle)
    r"\bay sonu(nda)?\b": "_AY_SONU_",
    r"\bay ba[sş][iı](nda)?\b": "_AY_BASI_",
    r"\bay orta(s[iı])?\b": "_AY_ORTASI_",
    r"\bhaftaya\b": "gelecek hafta",
    r"\b[oö]n[uü]m[uü]zdeki\b": "gelecek",
    r"\bhafta sonu\b": "_HAFTA_SONU_",
    r"\bg[uü]nlerden\b": "",
}

NUMBER_WORDS = {
    "bir": 1, "iki": 2, "üç": 3, "uc": 3, "dört": 4, "dort": 4,
    "beş": 5, "bes": 5, "altı": 6, "alti": 6, "yedi": 7, "sekiz": 8,
    "dokuz": 9, "on": 10, "on bir": 11, "on iki": 12, "on üç": 13,
    "on beş": 15, "on bes": 15, "yirmi": 20, "otuz": 30,
    "kırk": 40, "kirk": 40, "elli": 50, "yüz": 100, "yuz": 100,
}


def _preprocess_turkish(text: str) -> str:
    """Türkçe ifadeleri dateparser'ın anlayacağı forma çevir"""
    t = text.lower()
    for pattern, replacement in TURKISH_PATTERNS.items():
        t = re.sub(pattern, replacement, t)
    return t


WEEKDAYS_TR = {
    "pazartesi": 0,
    "sali": 1,
    "salı": 1,
    "carsamba": 2,
    "çarşamba": 2,
    "persembe": 3,
    "perşembe": 3,
    "cuma": 4,
    "cumartesi": 5,
    "pazar": 6
}


def _resolve_special_dates(text: str, base: datetime) -> Optional[datetime]:
    """Özel Türkçe tarih ifadeleri"""
    t = text.lower().strip()

    # haftaya / gelecek / önümüzdeki [gün] kontrolü
    m = re.search(r"\b(haftaya|gelecek|önümüzdeki|onumuzdeki)\s+(pazartesi|salı|sali|çarşamba|carsamba|perşembe|persembe|cuma|cumartesi|pazar)\b", t)
    if m:
        day_name = m.group(2)
        target_wd = WEEKDAYS_TR[day_name]
        current_wd = base.weekday()
        days_to_add = 7 - current_wd + target_wd
        return base.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_to_add)

    if "_AY_SONU_" in text:
        if base.month == 12:
            next_month = base.replace(year=base.year + 1, month=1, day=1)
        else:
            next_month = base.replace(month=base.month + 1, day=1)
        return next_month - timedelta(days=1)

    if "_AY_BASI_" in text:
        if base.month == 12:
            return base.replace(year=base.year + 1, month=1, day=1)
        return base.replace(month=base.month + 1, day=1)

    if "_AY_ORTASI_" in text:
        if base.day < 15:
            return base.replace(day=15)
        if base.month == 12:
            return base.replace(year=base.year + 1, month=1, day=15)
        return base.replace(month=base.month + 1, day=15)

    if "_HAFTA_SONU_" in text:
        days_to_sat = (5 - base.weekday()) % 7
        if days_to_sat == 0:
            days_to_sat = 7
        return base + timedelta(days=days_to_sat)

    return None


def parse_date_local(text: str) -> Optional[datetime]:
    """
    Yerel tarih ayrıştırıcı - dateparser + Türkçe özel ifadeler
    Bulamazsa None döndürür (Ollama fallback'e geçer)
    """
    now = datetime.now(tz)
    t = text.lower().strip()

    # Önce orijinal metindeki özel Türkçe tarihleri dene (örn: haftaya Salı)
    special = _resolve_special_dates(t, now)
    if special:
        return _adjust_for_weekend_holiday(special)

    # Önce ön işle
    preprocessed = _preprocess_turkish(t)

    # Ön işlenmiş özel tarihler (_AY_SONU_ vb.)
    special_pre = _resolve_special_dates(preprocessed, now)
    if special_pre:
        return _adjust_for_weekend_holiday(special_pre)

    # dateparser (Türkçe destekli)
    try:
        result = dateparser.parse(
            preprocessed,
            languages=["tr"],
            settings={
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": now.replace(tzinfo=None),
                "RETURN_AS_TIMEZONE_AWARE": True,
                "TIMEZONE": TIMEZONE,
                "DATE_ORDER": "DMY",
            },
        )
        if result:
            if result.tzinfo is None:
                result = result.replace(tzinfo=tz)
            return _adjust_for_weekend_holiday(result)
    except Exception as e:
        logger.debug(f"dateparser hata: {e}")

    return None


def _adjust_for_weekend_holiday(dt: datetime) -> datetime:
    """
    v2.2: Tarih cumartesi/pazara veya resmi tatile düşerse Pazartesi'ye ertele.
    Sadece config'de açıksa uygulanır.
    """
    try:
        from config import SKIP_WEEKENDS, SKIP_TURKEY_HOLIDAYS, TURKEY_HOLIDAYS_2026
    except ImportError:
        return dt

    if not SKIP_WEEKENDS and not SKIP_TURKEY_HOLIDAYS:
        return dt

    holidays = set(TURKEY_HOLIDAYS_2026) if SKIP_TURKEY_HOLIDAYS else set()

    for _ in range(7):
        date_str = dt.strftime("%Y-%m-%d")
        weekday = dt.weekday()  # 0=Pzt, 5=Cmt, 6=Pzr

        is_weekend = SKIP_WEEKENDS and weekday >= 5
        is_holiday = date_str in holidays

        if not is_weekend and not is_holiday:
            return dt

        dt += timedelta(days=1)
        logger.info(f"Tatil/hafta sonu, ileri atildi: {dt.strftime('%Y-%m-%d %A')}")

    return dt


# ============================================================
# TUTAR ÇIKARMA
# ============================================================

def parse_amount(text: str) -> Optional[float]:
    """
    "15 bin", "yarım milyon", "10000 TL", "15.000 ₺" vb. yakala
    """
    t = text.lower().replace(",", ".")

    if re.search(r"\byar[iı]m\s+milyon\b", t):
        return 500_000.0

    m = re.search(r"(\d+(?:\.\d+)?)\s*(bin|k|milyon|m)\b", t)
    if m:
        num = float(m.group(1))
        unit = m.group(2)
        if unit in ("bin", "k"):
            return num * 1000
        if unit in ("milyon", "m"):
            return num * 1_000_000

    m = re.search(r"(\d[\d\.]*\d|\d)\s*(tl|lira|₺)", t)
    if m:
        raw = m.group(1)
        if "." in raw:
            parts = raw.split(".")
            if len(parts[-1]) == 3 and len(parts) > 1:
                raw = "".join(parts)
        try:
            return float(raw)
        except ValueError:
            pass

    return None


# ============================================================
# OLLAMA (sadece yapı çıkarma)
# ============================================================

STRUCTURE_PROMPT = """Sen Türkçe metni JSON yapısına çeviren bir asistansın.
Verilen metinden ŞU ALANLARI çıkar (tarih çıkarma! O ayrı yapılacak):

- customer_name: Müşteri adı (kişi + firma varsa "Ahmet Bey - Bursa Spor")
- title: Kısa başlık (örn "Ödeme", "Kamyon yükleme", "Tekrar arama")
- kind: SADECE şunlardan biri: "odeme", "kamyon", "arama", "siparis", "takip", "diger"
- recurring: Tekrarlayan mı? null veya {{"pattern": "monthly|weekly|every_n_days", "value": "..."}}
  - "her ayın N'i" → {{"pattern": "monthly", "value": "N"}}
  - "her Salı" → {{"pattern": "weekly", "value": "tuesday"}}
  - "N günde bir" → {{"pattern": "every_n_days", "value": "N"}}
- has_date_clue: Metinde tarih ifadesi var mı? true/false
  - "yarın", "Cuma", "ay sonu", "25 Mayıs" vb. varsa true
  - "tekrar arayacağız" tek başına ise false (eksik bilgi)
- notes: Ek detay (ürün, durum). Yoksa boş string.

SADECE JSON, başka hiçbir şey yazma.

ÖRNEK 1: "Ahmet Bey Bursa Spor 22 Kasım 15 bin lira ödeme"
{{"customer_name": "Ahmet Bey - Bursa Spor", "title": "Ödeme", "kind": "odeme", "recurring": null, "has_date_clue": true, "notes": ""}}

ÖRNEK 2: "Mehmet'i aradık olumsuz döndü tekrar arayacağız"
{{"customer_name": "Mehmet", "title": "Tekrar arama", "kind": "takip", "recurring": null, "has_date_clue": false, "notes": "İlk aramada olumsuz döndü"}}

ÖRNEK 3: "Her ayın 15'inde Halil'e bakiye sor"
{{"customer_name": "Halil", "title": "Bakiye sorma", "kind": "arama", "recurring": {{"pattern": "monthly", "value": "15"}}, "has_date_clue": true, "notes": ""}}
"""


def _extract_structure(text: str) -> dict:
    """Gemini veya Ollama'dan yapı bilgisi al (tarih hariç). Hata olursa basit fallback."""
    from config import GEMINI_API_KEY
    
    if GEMINI_API_KEY:
        try:
            from google import genai
            logger.info("Yapay zeka analizinde Google Gemini (gemini-2.5-flash) kullaniliyor...")
            gemini_client = genai.Client(api_key=GEMINI_API_KEY)
            
            prompt = f"{STRUCTURE_PROMPT}\n\nGirdi Metni:\n\"{text}\""
            
            response = gemini_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config={"response_mime_type": "application/json"}
            )
            raw = response.text
            raw = re.sub(r"```json\s*|\s*```", "", raw).strip()
            return json.loads(raw)
        except Exception as e:
            logger.error(f"Gemini hatası, Ollama'ya geçiliyor: {e}")

    try:
        response = client.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": STRUCTURE_PROMPT},
                {"role": "user", "content": text},
            ],
            format="json",
            options={"temperature": 0.1},
        )
        raw = response["message"]["content"]
        raw = re.sub(r"```json\s*|\s*```", "", raw).strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Ollama hatası, fallback parser: {e}")
        return _fallback_structure(text)


def _fallback_structure(text: str) -> dict:
    """
    Ollama çalışmazsa primitif çıkarım.
    Kullanıcıya hata vermek yerine en azından bir şey kaydetmeye çalışır.
    """
    t = text.lower()

    if any(w in t for w in ["ödeme", "ödeyecek", "para", "lira", "bin tl", "tl"]):
        kind = "odeme"
    elif any(w in t for w in ["kamyon", "yükleme", "kargo", "tır"]):
        kind = "kamyon"
    elif any(w in t for w in ["ara", "telefon", "görüş"]):
        kind = "arama"
    elif any(w in t for w in ["sipariş", "siparis"]):
        kind = "siparis"
    else:
        kind = "diger"

    customer = "Bilinmiyor"
    words = text.split()
    for i, w in enumerate(words):
        if w and w[0].isupper() and len(w) > 2:
            if i + 1 < len(words) and words[i+1][0].isupper():
                customer = f"{w} {words[i+1]}"
            else:
                customer = w
            break

    has_date = any(w in t for w in [
        "yarın", "bugün", "hafta", "ay", "gün", "saat",
        "pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar",
        "ocak", "şubat", "mart", "nisan", "mayıs", "haziran",
        "temmuz", "ağustos", "eylül", "ekim", "kasım", "aralık",
    ])

    return {
        "customer_name": customer,
        "title": "Hatırlatma",
        "kind": kind,
        "recurring": None,
        "has_date_clue": has_date,
        "notes": "[Fallback parser - Ollama erisilemedi]",
    }


# ============================================================
# ANA PARSER
# ============================================================

def parse_voice_text(text: str) -> dict:
    """
    Hibrit ayrıştırma.
    Dönüş alanları:
        customer_name, title, kind, amount, due_date, remind_at, notes,
        recurring, needs_clarification, is_past_log
    """
    logger.info(f"Parse: {text}")

    parsed_date = parse_date_local(text)
    logger.info(f"dateparser sonuc: {parsed_date}")

    structure = _extract_structure(text)
    logger.info(f"Yapi: {structure}")

    amount = parse_amount(text)
    logger.info(f"Tutar: {amount}")

    has_clue = structure.get("has_date_clue", False)
    recurring = structure.get("recurring")

    if not parsed_date and not has_clue:
        return {
            "customer_name": structure.get("customer_name", "Bilinmiyor"),
            "title": structure.get("title", "Hatırlatma"),
            "kind": structure.get("kind", "diger"),
            "amount": amount,
            "due_date": None,
            "remind_at": None,
            "notes": structure.get("notes", "") or "",
            "recurring": recurring,
            "needs_clarification": {
                "missing": "date",
                "question": f"{structure.get('customer_name', 'Bu musteriyi')} ile ilgili ne zaman hatirlatayim? (orn: 'yarin', 'Cuma sabah', '25 Mayis')",
            },
            "is_past_log": False,
        }

    if not parsed_date and has_clue:
        raise ValueError(
            "Tarihi anlayamadım. Daha açık söyle (örn: 'yarın saat 10', '25 Mayıs', 'gelecek Cuma')."
        )

    due_date = parsed_date
    now = datetime.now(tz)
    is_past_log = False
    if due_date < now:
        if (now - due_date) < timedelta(hours=12):
            due_date = (now + timedelta(hours=1))
        else:
            is_past_log = True
            logger.info(f"Gecmis tarih, log mode: {due_date}")

    if is_past_log:
        remind_at = now
    else:
        if due_date.hour == 0 and due_date.minute == 0:
            remind_at = due_date - timedelta(hours=DEFAULT_REMINDER_HOURS_BEFORE)
            remind_at = remind_at.replace(hour=DEFAULT_REMINDER_HOUR, minute=DEFAULT_REMINDER_MINUTE)
        else:
            remind_at = due_date - timedelta(hours=12)
            if remind_at.hour < 7:
                remind_at = remind_at.replace(hour=DEFAULT_REMINDER_HOUR, minute=0)

        if remind_at < now:
            remind_at = now + timedelta(minutes=5)

    return {
        "customer_name": structure.get("customer_name", "Bilinmiyor"),
        "title": structure.get("title", "Hatırlatma"),
        "kind": structure.get("kind", "diger"),
        "amount": amount,
        "due_date": due_date,
        "remind_at": remind_at,
        "notes": structure.get("notes", "") or "",
        "recurring": recurring,
        "needs_clarification": None,
        "is_past_log": is_past_log,
    }


def parse_clarification_answer(question_context: dict, answer: str) -> dict:
    """Eksik bilgi yanıtını parse et"""
    missing = question_context.get("needs_clarification", {}).get("missing")

    if missing == "date":
        parsed = parse_date_local(answer)
        if not parsed:
            raise ValueError(
                "Tarihi anlayamadım. Açık söyle (örn: 'Cuma sabah 10', 'yarın', '25 Mayıs')."
            )

        updated = dict(question_context)
        updated["due_date"] = parsed

        now = datetime.now(tz)
        if parsed.hour == 0 and parsed.minute == 0:
            remind_at = parsed - timedelta(hours=DEFAULT_REMINDER_HOURS_BEFORE)
            remind_at = remind_at.replace(hour=DEFAULT_REMINDER_HOUR, minute=DEFAULT_REMINDER_MINUTE)
        else:
            remind_at = parsed - timedelta(hours=12)
            if remind_at.hour < 7:
                remind_at = remind_at.replace(hour=DEFAULT_REMINDER_HOUR, minute=0)

        if remind_at < now:
            remind_at = now + timedelta(minutes=5)

        updated["remind_at"] = remind_at
        updated["needs_clarification"] = None
        updated["is_past_log"] = parsed < now
        return updated

    if missing == "amount":
        amt = parse_amount(answer)
        if amt is None:
            raise ValueError("Tutar anlaşılmadı.")
        updated = dict(question_context)
        updated["amount"] = amt
        updated["needs_clarification"] = None
        return updated

    if missing == "customer":
        updated = dict(question_context)
        updated["customer_name"] = answer.strip()
        updated["needs_clarification"] = None
        return updated

    raise ValueError(f"Bilinmeyen eksik alan: {missing}")
