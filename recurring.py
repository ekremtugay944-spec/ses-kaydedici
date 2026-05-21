"""
Tekrarlayan hatırlatma motoru - v2.2
- monthly: her ayın N'inde
- weekly: her N gününde
- every_n_days: her N günde bir
"""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import db
from config import TIMEZONE

logger = logging.getLogger(__name__)
tz = ZoneInfo(TIMEZONE)

WEEKDAY_MAP = {
    "monday": 0, "pazartesi": 0,
    "tuesday": 1, "salı": 1, "sali": 1,
    "wednesday": 2, "çarşamba": 2, "carsamba": 2,
    "thursday": 3, "perşembe": 3, "persembe": 3,
    "friday": 4, "cuma": 4,
    "saturday": 5, "cumartesi": 5,
    "sunday": 6, "pazar": 6,
}


def calculate_next_due(pattern: str, value: str, from_date: datetime) -> datetime:
    """
    Bir sonraki vade tarihini hesapla
    """
    if pattern == "monthly":
        day = int(value)
        # Bu ayın N'i geçmişse → gelecek ay
        candidate = from_date.replace(day=min(day, 28))  # 28 garantili
        if candidate <= from_date:
            if from_date.month == 12:
                candidate = candidate.replace(year=from_date.year + 1, month=1)
            else:
                candidate = candidate.replace(month=from_date.month + 1)
        # Daha uzun aylar için gerçek günü dene
        try:
            candidate = candidate.replace(day=day)
        except ValueError:
            # Şubat 30'u gibi → ayın son günü
            pass
        return candidate.replace(hour=9, minute=0, second=0, microsecond=0)

    if pattern == "weekly":
        target_wd = WEEKDAY_MAP.get(value.lower())
        if target_wd is None:
            raise ValueError(f"Bilinmeyen gün: {value}")
        days_ahead = (target_wd - from_date.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7  # Aynı günse gelecek hafta
        candidate = from_date + timedelta(days=days_ahead)
        return candidate.replace(hour=9, minute=0, second=0, microsecond=0)

    if pattern == "every_n_days":
        n = int(value)
        candidate = from_date + timedelta(days=n)
        return candidate.replace(hour=9, minute=0, second=0, microsecond=0)

    raise ValueError(f"Bilinmeyen tekrar deseni: {pattern}")


def materialize_due_recurring():
    """
    Vadesi gelmiş tekrarlayan kurallar için somut hatırlatma oluştur.
    Her gece çalışır.
    """
    now = datetime.now(tz)
    due_rules = db.get_due_recurring(now)

    if not due_rules:
        return 0

    count = 0
    for rule in due_rules:
        next_due = rule["next_due"]
        if isinstance(next_due, str):
            next_due = datetime.fromisoformat(next_due)
        if next_due.tzinfo is None:
            next_due = next_due.replace(tzinfo=tz)

        # Hatırlatma için somut kayıt oluştur
        remind_at = next_due.replace(
            hour=rule.get("reminder_hour", 9), minute=0, second=0, microsecond=0
        )

        rid = db.add_reminder(
            customer_name=rule["customer_name"],
            title=rule["title"] + " (tekrar)",
            kind=rule["kind"],
            amount=rule["amount"],
            due_date=next_due,
            remind_at=remind_at,
            notes=rule.get("notes", "") or "",
            recurring_id=rule["id"],
        )
        logger.info(f"Tekrarlayan #{rule['id']} → hatırlatma #{rid} oluşturuldu")

        # Sonraki vadeyi hesapla
        try:
            next_next = calculate_next_due(rule["pattern"], rule["pattern_value"], next_due)
            db.update_recurring_next(rule["id"], next_next)
        except Exception as e:
            logger.error(f"Sonraki vade hesaplanamadı (kural {rule['id']}): {e}")
            db.deactivate_recurring(rule["id"])

        count += 1

    return count


def format_recurring_text(pattern: str, value: str) -> str:
    """İnsan okur formatında"""
    if pattern == "monthly":
        return f"Her ayın {value}'inde"
    if pattern == "weekly":
        gun_map = {
            "monday": "Pazartesi", "tuesday": "Salı", "wednesday": "Çarşamba",
            "thursday": "Perşembe", "friday": "Cuma", "saturday": "Cumartesi",
            "sunday": "Pazar",
            "pazartesi": "Pazartesi", "salı": "Salı", "çarşamba": "Çarşamba",
            "perşembe": "Perşembe", "cuma": "Cuma", "cumartesi": "Cumartesi",
            "pazar": "Pazar",
        }
        return f"Her {gun_map.get(value.lower(), value)}"
    if pattern == "every_n_days":
        return f"Her {value} günde bir"
    return f"{pattern} {value}"
