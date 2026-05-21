"""
Hatırlatma zamanlayıcısı - v2.1
İşler:
1. Her dakika: vadesi gelen hatırlatmalar (eskalasyonlu)
2. Her 5 dk: Apple Reminders iki yönlü senkron
3. Her gece 00:05: tekrarlayan materialize
4. Sabah 08:30: günlük özet
5. Akşam 19:00: kapanış raporu (yeni)
6. Her gece 03:00: ses arşivi temizliği (30 günden eskileri sil)
7. Her 10 dk: bekleyen konuşmaları temizle (30 dk timeout)
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import db
import apple_reminders
import recurring
from config import (
    TIMEZONE,
    DAILY_BRIEF_ENABLED, DAILY_BRIEF_HOUR, DAILY_BRIEF_MINUTE,
    EVENING_RECAP_ENABLED, EVENING_RECAP_HOUR, EVENING_RECAP_MINUTE,
    APPLE_REMINDERS_SYNC_INTERVAL_MIN,
    ESCALATION_HOURS_AFTER_FIRST, ESCALATION_NEXT_MORNING_HOUR,
    MAX_ESCALATIONS,
    AUDIO_ARCHIVE_DIR, AUDIO_ARCHIVE_DAYS,
    CONVERSATION_TIMEOUT_MIN,
)

logger = logging.getLogger(__name__)
tz = ZoneInfo(TIMEZONE)


KIND_EMOJI = {
    "odeme": "💰", "kamyon": "🚚", "arama": "📞",
    "siparis": "📦", "takip": "🔁", "diger": "📌",
}


def format_amount(amount):
    if amount is None:
        return ""
    return f"{amount:,.0f} ₺".replace(",", ".")


def format_phone_link(phone: str) -> str:
    if not phone:
        return ""
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("0"):
        digits = "90" + digits[1:]
    elif not digits.startswith("9"):
        digits = "90" + digits
    return f"https://wa.me/{digits}"


def build_action_keyboard(reminder_id: int, customer_name: str = "") -> InlineKeyboardMarkup:
    """v2.1: Inline butonlar - ID yazmaya gerek yok"""
    buttons = [
        [
            InlineKeyboardButton("✅ Tamamlandı", callback_data=f"done:{reminder_id}"),
            InlineKeyboardButton("⏰ 1 gün ertele", callback_data=f"snooze1:{reminder_id}"),
        ],
        [
            InlineKeyboardButton("⏰ 3 gün ertele", callback_data=f"snooze3:{reminder_id}"),
            InlineKeyboardButton("❌ İptal", callback_data=f"cancel:{reminder_id}"),
        ],
    ]
    if customer_name:
        buttons.append([
            InlineKeyboardButton(f"👤 {customer_name[:30]} kartı", callback_data=f"card:{customer_name[:50]}"),
        ])
    return InlineKeyboardMarkup(buttons)


def build_save_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    """Kayıt sonrası - geri al butonu"""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("↩️ Yanlış anlaşıldı, geri al", callback_data=f"undo:{reminder_id}"),
    ]])


def format_reminder_message(r: dict, escalation_level: int = 0) -> str:
    """Hatırlatma bildirimi"""
    emoji = KIND_EMOJI.get(r["kind"], "📌")
    due = r["due_date"]
    if isinstance(due, str):
        due = datetime.fromisoformat(due)

    # Eskalasyon başlığı
    if escalation_level == 0:
        header = f"{emoji} *HATIRLATMA*"
    elif escalation_level == 1:
        header = f"{emoji} *2. BİLDİRİM* (hâlâ açık)"
    else:
        header = f"{emoji} *3. BİLDİRİM — UNUTMA*"

    lines = [
        header,
        "",
        f"👤 *Müşteri:* {r['customer_name']}",
        f"📋 *Konu:* {r['title']}",
    ]
    if r.get("amount"):
        lines.append(f"💵 *Tutar:* {format_amount(r['amount'])}")
    lines.append(f"📅 *Vade:* {due.strftime('%d.%m.%Y %H:%M')}")

    customer = db.get_customer(r["customer_name"])
    if customer and customer.get("phone"):
        wa = format_phone_link(customer["phone"])
        lines.append(f"📞 *Telefon:* `{customer['phone']}`")
        if wa:
            lines.append(f"💬 [WhatsApp aç]({wa})")

    if r.get("notes"):
        lines.append(f"📝 *Not:* {r['notes']}")

    lines.append("")
    lines.append(f"🔢 ID: `{r['id']}`")
    return "\n".join(lines)


def format_daily_brief(reminders: list) -> str:
    if not reminders:
        return "🌅 *Günaydın Ekrem Bey*\n\nBugün için bekleyen hatırlatma yok. İyi günler! ☀️"

    odeme_count = sum(1 for r in reminders if r["kind"] == "odeme")
    kamyon_count = sum(1 for r in reminders if r["kind"] == "kamyon")
    arama_count = sum(1 for r in reminders if r["kind"] in ("arama", "takip"))
    diger_count = len(reminders) - odeme_count - kamyon_count - arama_count
    total_amount = sum(r["amount"] or 0 for r in reminders if r["kind"] == "odeme")

    lines = ["🌅 *Günaydın Ekrem Bey*", "", f"📊 *Bugün için {len(reminders)} hatırlatma:*"]
    if odeme_count:
        lines.append(f"  💰 {odeme_count} ödeme ({format_amount(total_amount)})")
    if kamyon_count:
        lines.append(f"  🚚 {kamyon_count} kamyon")
    if arama_count:
        lines.append(f"  📞 {arama_count} arama/takip")
    if diger_count:
        lines.append(f"  📌 {diger_count} diğer")

    lines.append("\n*Detay:*")
    for r in reminders:
        due = r["due_date"]
        if isinstance(due, str):
            due = datetime.fromisoformat(due)
        emoji = KIND_EMOJI.get(r["kind"], "📌")
        amt = f" ({format_amount(r['amount'])})" if r.get("amount") else ""
        lines.append(
            f"{emoji} `#{r['id']}` {due.strftime('%H:%M')} — *{r['customer_name']}*: {r['title']}{amt}"
        )
    lines.append("\nKomutlar: /liste /bugun /yarin /hafta")
    return "\n".join(lines)


def format_evening_recap(stats: dict) -> str:
    """v2.1: Akşam 19:00 kapanış raporu"""
    completed = stats["completed"]
    still_open = stats["still_open"]

    lines = ["🌆 *Akşam Raporu*", ""]

    if completed:
        total_collected = sum(c["amount"] or 0 for c in completed if c["kind"] == "odeme")
        lines.append(f"✅ *Bugün tamamlanan: {len(completed)}*")
        if total_collected > 0:
            lines.append(f"💰 Tahsilat: {format_amount(total_collected)}")
        lines.append("")
        for c in completed[:10]:
            emoji = KIND_EMOJI.get(c["kind"], "📌")
            amt = f" ({format_amount(c['amount'])})" if c.get("amount") else ""
            lines.append(f"{emoji} {c['customer_name']}: {c['title']}{amt}")
        lines.append("")
    else:
        lines.append("⚪ Bugün tamamlanan iş yok.\n")

    if still_open:
        total_pending = sum(o["amount"] or 0 for o in still_open if o["kind"] == "odeme")
        lines.append(f"🟡 *Hâlâ açık: {len(still_open)}*")
        if total_pending > 0:
            lines.append(f"💸 Bekleyen tahsilat: {format_amount(total_pending)}")
        lines.append("")
        for o in still_open[:10]:
            emoji = KIND_EMOJI.get(o["kind"], "📌")
            amt = f" ({format_amount(o['amount'])})" if o.get("amount") else ""
            lines.append(f"{emoji} `#{o['id']}` {o['customer_name']}: {o['title']}{amt}")
        lines.append("\n_Yarına aktarmadan tamamlamak istediklerin varsa şimdi bak._")
    else:
        lines.append("🎉 *Bugün için açık iş kalmadı, tebrikler!*")

    return "\n".join(lines)


class ReminderScheduler:
    def __init__(self, send_message_callback):
        self.scheduler = AsyncIOScheduler(timezone=tz)
        self.send_message = send_message_callback
        self.chat_ids = []

    def start(self, authorized_chat_ids: list):
        self.chat_ids = authorized_chat_ids

        # 1. Vade kontrolü (her dakika)
        self.scheduler.add_job(
            self.check_due_reminders, IntervalTrigger(minutes=1),
            id="check_reminders", replace_existing=True,
        )

        # 2. Apple Reminders senkronu
        self.scheduler.add_job(
            self.sync_apple_reminders,
            IntervalTrigger(minutes=APPLE_REMINDERS_SYNC_INTERVAL_MIN),
            id="apple_sync", replace_existing=True,
        )

        # 3. Tekrarlayan materialize
        self.scheduler.add_job(
            self.materialize_recurring,
            CronTrigger(hour=0, minute=5, timezone=tz),
            id="recurring", replace_existing=True,
        )

        # 4. Sabah özeti
        if DAILY_BRIEF_ENABLED:
            self.scheduler.add_job(
                self.send_daily_brief,
                CronTrigger(hour=DAILY_BRIEF_HOUR, minute=DAILY_BRIEF_MINUTE, timezone=tz),
                id="daily_brief", replace_existing=True,
            )

        # 5. Akşam raporu (yeni)
        if EVENING_RECAP_ENABLED:
            self.scheduler.add_job(
                self.send_evening_recap,
                CronTrigger(hour=EVENING_RECAP_HOUR, minute=EVENING_RECAP_MINUTE, timezone=tz),
                id="evening_recap", replace_existing=True,
            )

        # 6. Ses arşivi temizliği (her gece 03:00)
        self.scheduler.add_job(
            self.cleanup_audio_archive,
            CronTrigger(hour=3, minute=0, timezone=tz),
            id="audio_cleanup", replace_existing=True,
        )

        # 7. Bekleyen konuşma temizliği (her 10 dk)
        self.scheduler.add_job(
            self.cleanup_conversations, IntervalTrigger(minutes=10),
            id="conv_cleanup", replace_existing=True,
        )

        # 8. v2.2: Eski voice_ledger temizliği (haftalık)
        self.scheduler.add_job(
            self.cleanup_voice_ledger,
            CronTrigger(day_of_week="sun", hour=4, minute=0, timezone=tz),
            id="voice_ledger_cleanup", replace_existing=True,
        )

        self.scheduler.start()
        logger.info("Zamanlayıcı başladı (8 iş)")

    async def check_due_reminders(self):
        """v2.1: Eskalasyonlu hatırlatma gönderimi"""
        now = datetime.now(tz)
        due = db.get_due_reminders(now)
        if not due:
            return

        for r in due:
            esc = r.get("escalation_count") or 0
            if esc >= MAX_ESCALATIONS:
                # Maksimuma ulaştı, 24 saat ileri at, sayacı sıfırla
                db.snooze_reminder(r["id"], now + timedelta(hours=24))
                db.update_reminder(r["id"], escalation_count=0)
                continue

            msg = format_reminder_message(r, escalation_level=esc)
            keyboard = build_action_keyboard(r["id"], r["customer_name"])
            for chat_id in self.chat_ids:
                try:
                    await self.send_message(chat_id, msg, reply_markup=keyboard)
                except Exception as e:
                    logger.error(f"Hatırlatma gönderilemedi: {e}")

            # Bir sonraki eskalasyon zamanı
            new_esc = esc + 1
            if new_esc == 1:
                # 2 saat sonra tekrar
                next_remind = now + timedelta(hours=ESCALATION_HOURS_AFTER_FIRST)
            elif new_esc == 2:
                # Ertesi gün sabah 09:00
                next_morning = (now + timedelta(days=1)).replace(
                    hour=ESCALATION_NEXT_MORNING_HOUR, minute=0, second=0, microsecond=0
                )
                next_remind = next_morning
            else:
                # 24 saat
                next_remind = now + timedelta(hours=24)

            db.update_reminder(
                r["id"],
                escalation_count=new_esc,
                last_notified_at=now,
                remind_at=next_remind,
            )

    async def sync_apple_reminders(self):
        """v2.2: İki yönlü senkron + tarih senkronu"""
        if not apple_reminders.is_available():
            return
        try:
            apple_state = apple_reminders.get_two_way_sync_state()
            if not apple_state:
                return

            db_reminders = db.get_reminders_with_apple_id()

            for r in db_reminders:
                apple_id = r["apple_reminder_id"]
                if apple_id not in apple_state:
                    # Apple'da silinmiş → DB'de iptal et
                    if r["status"] == "open":
                        db.mark_cancelled(r["id"])
                        logger.info(f"Apple'da silinmiş #{r['id']} → iptal")
                        for chat_id in self.chat_ids:
                            try:
                                await self.send_message(
                                    chat_id,
                                    f"🗑️ iPhone'da silinmiş: *{r['customer_name']}* — {r['title']}",
                                )
                            except Exception:
                                pass
                    continue

                apple_item = apple_state[apple_id]

                # 1. Tamamlama senkronu
                if apple_item["completed"] and r["status"] == "open":
                    db.mark_done(r["id"], note="iPhone Reminders'tan kapatıldı")
                    logger.info(f"Apple tamamladı #{r['id']}")
                    for chat_id in self.chat_ids:
                        try:
                            await self.send_message(
                                chat_id,
                                f"📱 iPhone'da tamamlandı: *{r['customer_name']}* — {r['title']}",
                            )
                        except Exception:
                            pass
                    continue

                # 2. v2.2: Tarih değişikliği senkronu
                if r["status"] == "open" and apple_item.get("due_date"):
                    apple_due = apple_item["due_date"]
                    if apple_due.tzinfo is None:
                        apple_due = apple_due.replace(tzinfo=tz)

                    db_due = r["remind_at"]
                    if isinstance(db_due, str):
                        db_due = datetime.fromisoformat(db_due)
                    if db_due.tzinfo is None:
                        db_due = db_due.replace(tzinfo=tz)

                    # 1 dakikadan fazla fark varsa güncelle
                    diff = abs((apple_due - db_due).total_seconds())
                    if diff > 60:
                        db.update_reminder(r["id"], remind_at=apple_due)
                        logger.info(f"Apple tarih değişikliği yansıdı #{r['id']}: {apple_due}")
                        for chat_id in self.chat_ids:
                            try:
                                await self.send_message(
                                    chat_id,
                                    f"📱 iPhone'da tarih değişti: *{r['customer_name']}*\n"
                                    f"Yeni: {apple_due.strftime('%d.%m.%Y %H:%M')}",
                                )
                            except Exception:
                                pass
        except Exception as e:
            logger.error(f"Apple sync hatası: {e}")

    async def materialize_recurring(self):
        try:
            count = recurring.materialize_due_recurring()
            if count > 0:
                logger.info(f"{count} tekrar materialize edildi")
        except Exception as e:
            logger.error(f"Recurring hatası: {e}")

    async def send_daily_brief(self):
        now = datetime.now(tz)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        reminders = db.get_reminders_between(start, end)
        msg = format_daily_brief(reminders)
        for chat_id in self.chat_ids:
            try:
                await self.send_message(chat_id, msg)
            except Exception as e:
                logger.error(f"Sabah özeti gönderilemedi: {e}")

    async def send_evening_recap(self):
        """v2.1: Akşam kapanış raporu"""
        stats = db.get_today_stats()
        msg = format_evening_recap(stats)
        for chat_id in self.chat_ids:
            try:
                await self.send_message(chat_id, msg)
            except Exception as e:
                logger.error(f"Akşam raporu gönderilemedi: {e}")

    async def cleanup_audio_archive(self):
        """v2.1: 30 günden eski ses dosyalarını sil"""
        cutoff = datetime.now() - timedelta(days=AUDIO_ARCHIVE_DAYS)
        try:
            deleted = 0
            for f in AUDIO_ARCHIVE_DIR.glob("*"):
                if f.is_file() and datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                    f.unlink()
                    deleted += 1
            if deleted:
                logger.info(f"{deleted} eski ses dosyası temizlendi")
        except Exception as e:
            logger.error(f"Ses temizliği hatası: {e}")

    async def cleanup_conversations(self):
        """v2.1: Bekleyen konuşmaları temizle"""
        try:
            db.cleanup_stale_conversations(CONVERSATION_TIMEOUT_MIN)
        except Exception as e:
            logger.error(f"Konuşma temizliği hatası: {e}")

    async def cleanup_voice_ledger(self):
        """v2.2: 7 günden eski voice_ledger kayıtlarını temizle"""
        try:
            db.cleanup_old_voice_ledger(days=7)
        except Exception as e:
            logger.error(f"Voice ledger temizliği hatası: {e}")

    def stop(self):
        self.scheduler.shutdown()
