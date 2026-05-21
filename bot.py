"""
Gözde Plastik - Müşteri Hatırlatma Botu v2.1
"""
import asyncio
import json
import logging
import logging.handlers
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

import db
import config
import whisper_local
import parser
import apple_reminders
import customer_import
import recurring
from scheduler import (
    ReminderScheduler, format_reminder_message, format_daily_brief,
    format_amount, format_phone_link, KIND_EMOJI,
    build_action_keyboard, build_save_keyboard,
)

# ============================================================
# LOG
# ============================================================
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(
            config.LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("bot")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

tz = ZoneInfo(config.TIMEZONE)


# ============================================================
# MESAJ YARDIMCILARI (v2.2)
# ============================================================

def split_long_message(text: str, max_length: int = None) -> list:
    """
    Uzun mesajları Telegram'ın 4096 karakter sınırına göre böl.
    Markdown bozulmasın diye satır bazlı bölünür.
    """
    max_length = max_length or config.TELEGRAM_MAX_MESSAGE_LENGTH
    if len(text) <= max_length:
        return [text]

    parts = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_length:
            if current:
                parts.append(current)
            current = line + "\n"
        else:
            current += line + "\n"
    if current:
        parts.append(current.rstrip())
    return parts


async def send_long(update, text: str, **kwargs):
    """Uzun mesajları parçalayarak gönder"""
    parts = split_long_message(text)
    for i, part in enumerate(parts):
        suffix = f"\n_({i+1}/{len(parts)})_" if len(parts) > 1 else ""
        try:
            await update.message.reply_text(
                part + suffix,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
                **kwargs,
            )
        except Exception as e:
            logger.error(f"Mesaj gönderme hatası: {e}")
            # Markdown'sız tekrar dene
            try:
                await update.message.reply_text(part + suffix)
            except Exception:
                pass


# ============================================================
# YETKİ
# ============================================================

def authorized(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if config.AUTHORIZED_CHAT_IDS and chat_id not in config.AUTHORIZED_CHAT_IDS:
            await update.message.reply_text(
                f"⛔ Yetkili değilsin.\nChat ID'in: `{chat_id}`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        return await func(update, context)
    return wrapper


def authorized_callback(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if config.AUTHORIZED_CHAT_IDS and chat_id not in config.AUTHORIZED_CHAT_IDS:
            await update.callback_query.answer("Yetkili değilsin.", show_alert=True)
            return
        return await func(update, context)
    return wrapper


# ============================================================
# YARDIMCI
# ============================================================

def save_reminder_and_sync(parsed: dict, original_text: str = "",
                           audio_archive_path: str = "") -> int:
    """Hatırlatmayı DB'ye + Apple Reminders'a yaz"""
    apple_id = None
    if apple_reminders.is_available() and not parsed.get("is_past_log"):
        amt_str = f" ({format_amount(parsed['amount'])})" if parsed.get("amount") else ""
        apple_title = f"{parsed['customer_name']} — {parsed['title']}{amt_str}"
        apple_id = apple_reminders.add_reminder(
            title=apple_title,
            due_date=parsed["remind_at"],
            notes=parsed.get("notes", "") or original_text,
        )

    rid = db.add_reminder(
        customer_name=parsed["customer_name"],
        title=parsed["title"],
        kind=parsed["kind"],
        amount=parsed.get("amount"),
        due_date=parsed["due_date"],
        remind_at=parsed["remind_at"],
        original_voice_text=original_text,
        notes=parsed.get("notes", "") or "",
        apple_reminder_id=apple_id,
        audio_path=audio_archive_path,
        is_past_log=parsed.get("is_past_log", False),
    )
    return rid


def format_save_confirmation(rid: int, parsed: dict, warnings: list = None) -> str:
    emoji = KIND_EMOJI.get(parsed["kind"], "📌")
    if parsed.get("is_past_log"):
        msg = f"📜 *Geçmiş kayıt eklendi #{rid}* _(hatırlatma yapılmayacak)_\n\n"
    else:
        msg = f"✅ *Kaydedildi #{rid}*\n\n"

    msg += f"{emoji} *Konu:* {parsed['title']}\n"
    msg += f"👤 *Müşteri:* {parsed['customer_name']}\n"

    if parsed.get("amount"):
        msg += f"💵 *Tutar:* {format_amount(parsed['amount'])}\n"

    msg += f"📅 *Vade:* {parsed['due_date'].strftime('%d.%m.%Y %H:%M')}\n"
    if not parsed.get("is_past_log"):
        msg += f"🔔 *Hatırlatma:* {parsed['remind_at'].strftime('%d.%m.%Y %H:%M')}\n"

    if parsed.get("notes"):
        msg += f"📝 *Not:* {parsed['notes']}\n"

    if apple_reminders.is_available() and not parsed.get("is_past_log"):
        msg += "📱 _iPhone Reminders'a da yazıldı_\n"

    # Akıllı bağlam uyarıları
    if warnings:
        msg += "\n"
        for w in warnings:
            msg += f"{w}\n"

    return msg


# ============================================================
# KOMUTLAR - bilgi
# ============================================================

@authorized
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Gözde Plastik Hatırlatma Botu v2.1*\n\n"
        "🎤 Sesli not at, otomatik kaydedeyim.\n"
        "✍️ Yazılı not da gönderebilirsin.\n"
        "📱 iPhone Reminders'a da yazılır, telefonun bildirim çalar.\n\n"
        "*Komutlar:* /help\n\n"
        f"Chat ID'in: `{update.effective_chat.id}`",
        parse_mode=ParseMode.MARKDOWN,
    )


@authorized
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*🎤 SESLİ ÖRNEKLER:*\n"
        "_\"Ahmet Bey 22 Kasım 15 bin lira ödeme\"_\n"
        "_\"Yarın sabah 8 Halil'in kamyonu\"_\n"
        "_\"Mehmet'i aradık olumsuz döndü tekrar arayacağız\"_ → tarihi sorar\n"
        "_\"Her ayın 15'inde Halil'e bakiye sor\"_ → tekrarlayan\n\n"
        "*ZAMAN:* /liste /bugun /yarin /hafta\n"
        "*KASA:* /kasa  /kasa hafta  /kasa ay\n"
        "*DURUM:* /dashboard (genel panel)\n"
        "*MÜŞTERİ:* /kart `<isim>` /musteri /risk /musteriler /riskli\n"
        "*NOT:* `/not Ahmet eski model isteyince başı belaya girer`\n"
        "*TEKRAR:* /tekrarli /sil\\_tekrar\\_`<ID>`\n"
        "*EXCEL:* /sablon /disa\\_aktar (sonra Excel yolla)\n"
        "*YEDEK:* /yedek  •  /istatistik  •  /version\n\n"
        "_Hatırlatma butonlarla yönetilir, ID yazmaya gerek yok._",
        parse_mode=ParseMode.MARKDOWN,
    )


@authorized
async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    apple_status = "✅ " + (apple_reminders.get_backend() or "kapalı") if apple_reminders.is_available() else "⚠️ kapalı"
    haiku_status = "✅ aktif" if config.USE_HAIKU and config.ANTHROPIC_API_KEY else "⚪ kapalı (opsiyonel)"
    await update.message.reply_text(
        f"*v2.2*\n\n"
        f"🧠 Whisper: `{config.WHISPER_MODEL}`\n"
        f"🤖 Ollama: `{config.OLLAMA_MODEL}`\n"
        f"💎 Haiku: {haiku_status}\n"
        f"🍎 Apple Reminders: {apple_status}\n"
        f"🌙 Saat dilimi: `{config.TIMEZONE}`\n"
        f"📅 Hafta sonu erteleme: {'✅' if config.SKIP_WEEKENDS else '⚪'}\n"
        f"🇹🇷 Bayram erteleme: {'✅' if config.SKIP_TURKEY_HOLIDAYS else '⚪'}",
        parse_mode=ParseMode.MARKDOWN,
    )


@authorized
async def cmd_durum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sistem durumu"""
    open_count = len(db.get_open_reminders())
    customers = db.list_customers(limit=10000)
    recurring_rules = db.get_active_recurring()
    audio_count = len(list(config.AUDIO_ARCHIVE_DIR.glob("*")))

    await update.message.reply_text(
        f"📊 *Sistem Durumu*\n\n"
        f"📋 Açık hatırlatma: {open_count}\n"
        f"👥 Kayıtlı müşteri: {len(customers)}\n"
        f"🔁 Aktif tekrarlayan: {len(recurring_rules)}\n"
        f"🎙 Arşivlenmiş ses: {audio_count}\n"
        f"📱 Apple Reminders: {'✅' if apple_reminders.is_available() else '⚠️ kapalı'}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ============================================================
# KOMUTLAR - listeleme
# ============================================================

@authorized
async def cmd_liste(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reminders = db.get_open_reminders()
    if not reminders:
        await update.message.reply_text("📭 Açık hatırlatma yok.")
        return
    lines = [f"📋 *Açık Hatırlatmalar ({len(reminders)})*\n"]
    for r in reminders:
        due = r["due_date"] if isinstance(r["due_date"], datetime) else datetime.fromisoformat(r["due_date"])
        emoji = KIND_EMOJI.get(r["kind"], "📌")
        amt = f" — {format_amount(r['amount'])}" if r.get("amount") else ""
        lines.append(f"{emoji} `#{r['id']}` {due.strftime('%d.%m %H:%M')} — *{r['customer_name']}*: {r['title']}{amt}")
    await send_long(update, "\n".join(lines))


@authorized
async def cmd_bugun(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    reminders = db.get_reminders_between(start, end)
    await update.message.reply_text(format_daily_brief(reminders), parse_mode=ParseMode.MARKDOWN)


async def _send_range(update, days_offset, days_count, title_prefix):
    now = datetime.now(tz)
    start = (now + timedelta(days=days_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days_count)
    reminders = db.get_reminders_between(start, end)
    if not reminders:
        await update.message.reply_text(f"📭 {title_prefix} için hatırlatma yok.")
        return
    lines = [f"{title_prefix} *({len(reminders)} hatırlatma)*\n"]
    for r in reminders:
        due = r["due_date"] if isinstance(r["due_date"], datetime) else datetime.fromisoformat(r["due_date"])
        emoji = KIND_EMOJI.get(r["kind"], "📌")
        amt = f" — {format_amount(r['amount'])}" if r.get("amount") else ""
        lines.append(f"{emoji} `#{r['id']}` {due.strftime('%a %d.%m %H:%M')} — *{r['customer_name']}*: {r['title']}{amt}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@authorized
async def cmd_yarin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_range(update, 1, 1, "📅 *Yarın*")


@authorized
async def cmd_hafta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_range(update, 0, 7, "📆 *Bu Hafta*")


# ============================================================
# KOMUTLAR - müşteri
# ============================================================

@authorized
async def cmd_kart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: `/kart Ahmet`", parse_mode=ParseMode.MARKDOWN)
        return
    query = " ".join(context.args)
    customer = db.find_customer_fuzzy(query)
    if not customer:
        await update.message.reply_text(f"📭 *{query}* bulunamadı.", parse_mode=ParseMode.MARKDOWN)
        return
    await _show_card(update, customer["name"])


async def _show_card(update_or_query, customer_name: str):
    summary = db.get_customer_summary(customer_name)
    if not summary:
        msg = f"📭 *{customer_name}* için detay yok."
        await _reply(update_or_query, msg)
        return

    created = summary["created_count"]
    delayed = summary["delayed_count"]
    rate = (delayed / created * 100) if created else 0
    if rate < config.RISK_LOW_THRESHOLD:
        risk_emoji, risk_text = "🟢", "DÜŞÜK"
    elif rate < config.RISK_HIGH_THRESHOLD:
        risk_emoji, risk_text = "🟡", "ORTA"
    else:
        risk_emoji, risk_text = "🔴", "YÜKSEK"

    lines = [f"👤 *{summary['name']}*", ""]
    if summary.get("phone"):
        wa = format_phone_link(summary["phone"])
        # v2.2: tel: linki (mobilde tıklayınca arar)
        digits = "".join(c for c in summary["phone"] if c.isdigit())
        if digits.startswith("0"):
            tel_link = f"tel:+90{digits[1:]}"
        elif digits.startswith("9"):
            tel_link = f"tel:+{digits}"
        else:
            tel_link = f"tel:+90{digits}"
        lines.append(f"📞 [`{summary['phone']}`]({tel_link})")
        if wa:
            lines.append(f"💬 [WhatsApp aç]({wa})")
    if summary.get("company"):
        lines.append(f"🏢 {summary['company']}")
    if summary.get("city"):
        lines.append(f"📍 {summary['city']}")
    if summary.get("segment"):
        lines.append(f"🏷️ {summary['segment']}")

    # v2.2: Cep notu en üstte göze çarpsın
    if summary.get("personal_note"):
        lines.append(f"\n📝 _{summary['personal_note']}_")

    lines.append("")
    lines.append(f"{risk_emoji} *Risk:* {risk_text} (%{rate:.0f} erteleme)")

    if summary["open_amount"]:
        lines.append(f"💰 *Açık alacak:* {format_amount(summary['open_amount'])}")
    if summary["collected_amount"]:
        lines.append(f"✅ *Tahsil:* {format_amount(summary['collected_amount'])}")

    lines.append(f"📋 *Açık:* {summary['open_count']}  |  Tamam: {summary['done_count']}")

    if summary.get("last_activity"):
        la = summary["last_activity"]
        if isinstance(la, str):
            la = datetime.fromisoformat(la)
        days = (datetime.now() - la.replace(tzinfo=None)).days
        lines.append(f"📅 Son aktivite: {days} gün önce")

    if summary.get("notes") and not summary.get("personal_note"):
        lines.append(f"\n_{summary['notes']}_")

    history = db.get_customer_history(summary["name"], limit=3)
    if history:
        lines.append("\n*Son hatırlatmalar:*")
        for r in history:
            due = r["due_date"] if isinstance(r["due_date"], datetime) else datetime.fromisoformat(r["due_date"])
            status_emoji = {"open": "🟡", "done": "✅", "cancelled": "❌"}.get(r["status"], "❓")
            lines.append(f"{status_emoji} `#{r['id']}` {due.strftime('%d.%m')} {r['title']}")

    await _reply(update_or_query, "\n".join(lines))


async def _reply(update_or_query, text: str):
    if hasattr(update_or_query, "message") and update_or_query.message:
        await update_or_query.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True,
        )
    elif hasattr(update_or_query, "edit_message_text"):
        await update_or_query.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True,
        )


@authorized
async def cmd_musteri(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: `/musteri Ahmet`", parse_mode=ParseMode.MARKDOWN)
        return
    name = " ".join(context.args)
    history = db.get_customer_history(name)
    if not history:
        await update.message.reply_text(f"📭 *{name}* için kayıt yok.", parse_mode=ParseMode.MARKDOWN)
        return
    lines = [f"👤 *{name} — Geçmiş ({len(history)})*\n"]
    for r in history[:30]:
        due = r["due_date"] if isinstance(r["due_date"], datetime) else datetime.fromisoformat(r["due_date"])
        status_emoji = {"open": "🟡", "done": "✅", "cancelled": "❌"}.get(r["status"], "❓")
        amt = f" — {format_amount(r['amount'])}" if r.get("amount") else ""
        lines.append(f"{status_emoji} `#{r['id']}` {due.strftime('%d.%m.%Y')} — {r['title']}{amt}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@authorized
async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Kullanım: `/risk Ahmet`", parse_mode=ParseMode.MARKDOWN)
        return
    name = " ".join(context.args)
    stats = db.get_customer_risk(name)
    total = stats["created"]
    if total == 0:
        await update.message.reply_text(f"📭 *{name}* için kayıt yok.", parse_mode=ParseMode.MARKDOWN)
        return
    rate = (stats["delayed"] / total * 100) if total else 0
    if rate < config.RISK_LOW_THRESHOLD:
        e, t = "🟢", "DÜŞÜK"
    elif rate < config.RISK_HIGH_THRESHOLD:
        e, t = "🟡", "ORTA"
    else:
        e, t = "🔴", "YÜKSEK"
    await update.message.reply_text(
        f"{e} *{name} — Risk: {t}*\n\n"
        f"Toplam: {total}, Tamam: {stats['completed']}, "
        f"Ertelenen: {stats['delayed']}, İptal: {stats['cancelled']}\n"
        f"Erteleme oranı: %{rate:.0f}",
        parse_mode=ParseMode.MARKDOWN,
    )


@authorized
async def cmd_musteriler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    customers = db.list_customers(limit=1000)
    if not customers:
        await update.message.reply_text("📭 Henüz müşteri yok. /sablon ile başla.")
        return
    lines = [f"👥 *Müşteriler ({len(customers)})*\n"]
    for c in customers:
        phone = f" — {c['phone']}" if c.get("phone") else ""
        lines.append(f"• {c['name']}{phone}")
    await send_long(update, "\n".join(lines))


@authorized
async def cmd_riskli(update: Update, context: ContextTypes.DEFAULT_TYPE):
    risky = db.get_top_risky_customers(limit=10)
    if not risky:
        await update.message.reply_text("📭 Yeterli veri yok.")
        return
    lines = ["🔴 *En Riskli Müşteriler*\n"]
    for r in risky:
        rate = (r["delayed"] / r["created"] * 100) if r["created"] else 0
        lines.append(f"• *{r['customer_name']}* — %{rate:.0f} ({r['delayed']}/{r['created']})")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ============================================================
# v2.2 YENİ KOMUTLAR
# ============================================================

@authorized
async def cmd_kasa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bugün/hafta/ay tahsilat özeti"""
    period = "today"
    if context.args:
        arg = context.args[0].lower()
        if arg in ("hafta", "week"):
            period = "week"
        elif arg in ("ay", "month"):
            period = "month"

    data = db.get_cash_summary(period)
    period_label = {"today": "Bugün", "week": "Bu Hafta", "month": "Bu Ay"}[period]

    lines = [f"💰 *Kasa — {period_label}*", ""]

    if data["collected"]:
        lines.append(f"✅ *Tahsil edilen: {format_amount(data['collected_total'])}*")
        lines.append(f"   ({len(data['collected'])} ödeme)")
        lines.append("")
        for c in data["collected"][:15]:
            comp = c.get("completed_at")
            if isinstance(comp, str):
                comp = datetime.fromisoformat(comp)
            t = comp.strftime("%d.%m %H:%M") if comp else ""
            lines.append(f"  • {t} *{c['customer_name']}*: {format_amount(c['amount'])}")
        if len(data["collected"]) > 15:
            lines.append(f"  _...{len(data['collected']) - 15} daha_")
    else:
        lines.append(f"⚪ {period_label} için tahsilat yok.")

    lines.append("")
    lines.append(f"🟡 *Açık alacak: {format_amount(data['open_total'])}*")
    lines.append(f"   ({len(data['open'])} bekleyen)")

    if data["open"]:
        lines.append("\n*En yakın vadeli:*")
        for o in data["open"][:5]:
            due = o.get("due_date")
            if isinstance(due, str):
                due = datetime.fromisoformat(due)
            t = due.strftime("%d.%m.%Y") if due else "?"
            lines.append(f"  • {t} *{o['customer_name']}*: {format_amount(o['amount'])}")

    lines.append("\n_Diğer: `/kasa hafta` veya `/kasa ay`_")
    await send_long(update, "\n".join(lines))


@authorized
async def cmd_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Genel durum dashboard'u"""
    d = db.get_dashboard_data()
    now = datetime.now(tz)

    lines = [
        f"📊 *Anlık Durum* — {now.strftime('%d.%m.%Y %H:%M')}",
        "",
        f"💰 *Toplam açık alacak:* {format_amount(d['total_open_amount'])}",
        f"   ({d['total_open_count']} bekleyen ödeme)",
        f"",
        f"📅 *Bu hafta vadesi gelen:* {format_amount(d['this_week_amount'])}",
        f"",
    ]

    if d["overdue_amount"] > 0:
        lines.append(f"⚠️ *Vadesi geçmiş:* {format_amount(d['overdue_amount'])} ({d['overdue_count']} adet)")
    if d["critical_overdue_amount"] > 0:
        lines.append(f"🔴 *90+ gün geçmiş:* {format_amount(d['critical_overdue_amount'])}")

    lines.append("")
    lines.append("📋 *Bu hafta yapılacak:*")
    week_data = d["week_by_kind"]
    if week_data:
        emoji_map = {"odeme": "💰", "kamyon": "🚚", "arama": "📞",
                     "siparis": "📦", "takip": "🔁", "diger": "📌"}
        for kind, count in week_data.items():
            emoji = emoji_map.get(kind, "📌")
            lines.append(f"  {emoji} {kind}: {count}")
    else:
        lines.append("  ⚪ Henüz iş yok")

    lines.append("")
    if d["risky_customer_count"] > 0:
        lines.append(f"🔴 *Riskli müşteri (50%+ erteleyen):* {d['risky_customer_count']}")
        lines.append("   _/riskli ile detay_")
    else:
        lines.append("🟢 Riskli müşteri yok")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@authorized
async def cmd_istatistik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot kullanım istatistikleri"""
    s = db.get_bot_stats()

    lines = [
        "📈 *Bot İstatistikleri*",
        "",
        f"🎤 Toplam ses kaydı: {s['total_voices']}",
        f"📋 Toplam hatırlatma: {s['total_reminders']}",
        f"   ├ Aktif: {s['active_reminders']}",
        f"   └ Tamamlanan: {s['completed_reminders']}",
        f"👥 Toplam müşteri: {s['total_customers']}",
        f"🔁 Aktif tekrarlayan: {s['recurring_rules']}",
    ]

    if s["first_record"]:
        first = s["first_record"]
        if isinstance(first, str):
            first = datetime.fromisoformat(first)
        days = (datetime.now() - first).days
        lines.append(f"📅 Kayıt başlangıcı: {first.strftime('%d.%m.%Y')} ({days} gün önce)")

        if s["completed_reminders"] > 0 and days > 0:
            avg = s["completed_reminders"] / days
            lines.append(f"   _Günde ortalama {avg:.1f} iş tamamlandı_")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@authorized
async def cmd_not(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Müşteriye cep notu ekle: /not Ahmet eski model isteyince başı belaya girer"""
    if len(context.args) < 2:
        await update.message.reply_text(
            "Kullanım: `/not <müşteri> <not metni>`\n\n"
            "Örnek: `/not Ahmet eski model 5 numarayı sevmiyor`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    name = context.args[0]
    note = " ".join(context.args[1:])

    candidates = db.find_customer_candidates(name)
    if not candidates:
        # Yeni müşteri olarak ekle, notu yaz
        db.upsert_customer(name, personal_note=note)
        await update.message.reply_text(
            f"✅ Yeni müşteri *{name}* eklendi, not kaydedildi.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    actual_name = candidates[0][0]["name"]
    db.set_personal_note(actual_name, note)
    await update.message.reply_text(
        f"✅ *{actual_name}* için cep notu kaydedildi:\n_{note}_",
        parse_mode=ParseMode.MARKDOWN,
    )


# ============================================================
# KOMUTLAR - tekrarlayan
# ============================================================

@authorized
async def cmd_tekrarli(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rules = db.get_active_recurring()
    if not rules:
        await update.message.reply_text("📭 Aktif tekrarlayan kural yok.")
        return
    lines = [f"🔁 *Tekrarlayan Kurallar ({len(rules)})*\n"]
    for r in rules:
        nd = r["next_due"]
        if isinstance(nd, str):
            nd = datetime.fromisoformat(nd)
        pattern_text = recurring.format_recurring_text(r["pattern"], r["pattern_value"])
        lines.append(
            f"• `#{r['id']}` *{r['customer_name']}*: {r['title']}\n"
            f"  {pattern_text} • Sonraki: {nd.strftime('%d.%m.%Y')}\n"
            f"  /sil\\_tekrar\\_{r['id']}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ============================================================
# KOMUTLAR - excel ve yedek
# ============================================================

@authorized
async def cmd_sablon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    path = config.IMPORT_DIR / "musteri_sablon.xlsx"
    customer_import.create_template(path)
    await update.message.reply_document(
        document=open(path, "rb"),
        filename="musteri_sablon.xlsx",
        caption="📋 Müşteri import şablonu. Doldur, Excel'i bana geri yolla.",
    )


@authorized
async def cmd_dis_aktar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    path = config.IMPORT_DIR / "musteriler_export.xlsx"
    count = customer_import.export_to_excel(path)
    if count == 0:
        await update.message.reply_text("📭 Henüz müşteri yok.")
        return
    await update.message.reply_document(
        document=open(path, "rb"),
        filename=f"musteriler_{datetime.now().strftime('%Y%m%d')}.xlsx",
        caption=f"📤 {count} müşteri.",
    )


@authorized
async def cmd_yedek(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """DB yedeği indir"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = config.BACKUP_DIR / f"reminders_{timestamp}.db"
    shutil.copy2(config.DB_PATH, backup_path)
    await update.message.reply_document(
        document=open(backup_path, "rb"),
        filename=backup_path.name,
        caption=f"💾 DB yedeği ({backup_path.stat().st_size // 1024} KB)",
    )


# ============================================================
# DOSYA ALMA - Excel
# ============================================================

@authorized
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.lower().endswith((".xlsx", ".xls")):
        await update.message.reply_text("⚠️ Sadece Excel kabul ediyorum.")
        return
    await update.message.reply_text("📥 Excel okunuyor...")
    try:
        file = await context.bot.get_file(doc.file_id)
        path = config.IMPORT_DIR / f"upload_{doc.file_id}.xlsx"
        await file.download_to_drive(path)
        added, updated, errors = await asyncio.to_thread(customer_import.import_from_excel, path)
        msg = f"✅ *Import tamam*\n\n➕ Eklenen: {added}\n♻️ Güncel: {updated}"
        if errors:
            msg += f"\n⚠️ Hata: {len(errors)}\n"
            for e in errors[:5]:
                msg += f"• {e}\n"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        try:
            path.unlink()
        except Exception:
            pass
    except Exception as e:
        logger.exception("Excel hatası")
        await update.message.reply_text(f"❌ {e}")


# ============================================================
# DİNAMİK KOMUTLAR - /sil_tekrar_X
# ============================================================

async def handle_dynamic_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower().strip() == "/iptal":
        db.clear_conversation_state(update.effective_chat.id)
        await update.message.reply_text("✅ İşlem iptal edildi.")
        return
    m = re.match(r"^/sil_tekrar_(\d+)$", text)
    if m:
        rid = int(m.group(1))
        db.deactivate_recurring(rid)
        await update.message.reply_text(f"✅ Tekrar #{rid} durduruldu.")
        return
    # Eski formatları da destekle (legacy)
    m = re.match(r"^/tamam_(\d+)$", text)
    if m:
        await _do_complete(update, int(m.group(1)))
        return
    m = re.match(r"^/iptal_(\d+)$", text)
    if m:
        await _do_cancel(update, int(m.group(1)))
        return
    await update.message.reply_text("❓ Komut anlaşılmadı. /help yaz.")


async def _do_complete(update, rid: int):
    r = db.get_reminder(rid)
    if not r:
        await update.message.reply_text(f"❌ #{rid} yok.")
        return
    db.mark_done(rid)
    if r.get("apple_reminder_id"):
        apple_reminders.complete_reminder(r["apple_reminder_id"])
    await update.message.reply_text(
        f"✅ *{r['customer_name']}* — {r['title']}", parse_mode=ParseMode.MARKDOWN,
    )


async def _do_cancel(update, rid: int):
    r = db.get_reminder(rid)
    if not r:
        await update.message.reply_text(f"❌ #{rid} yok.")
        return
    db.mark_cancelled(rid)
    if r.get("apple_reminder_id"):
        apple_reminders.delete_reminder(r["apple_reminder_id"])
    await update.message.reply_text(
        f"❌ İptal: *{r['customer_name']}*", parse_mode=ParseMode.MARKDOWN,
    )


# ============================================================
# INLINE KEYBOARD CALLBACK'leri
# ============================================================

@authorized_callback
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """v2.1: Buton tıklamaları"""
    query = update.callback_query
    await query.answer()
    data = query.data

    # done:123
    m = re.match(r"^done:(\d+)$", data)
    if m:
        rid = int(m.group(1))
        r = db.get_reminder(rid)
        if not r:
            await query.edit_message_text("❌ Bulunamadı.")
            return
        db.mark_done(rid)
        if r.get("apple_reminder_id"):
            apple_reminders.complete_reminder(r["apple_reminder_id"])
        await query.edit_message_text(
            f"✅ Tamamlandı: *{r['customer_name']}* — {r['title']}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # snooze1:123, snooze3:123
    m = re.match(r"^snooze(\d+):(\d+)$", data)
    if m:
        days = int(m.group(1))
        rid = int(m.group(2))
        r = db.get_reminder(rid)
        if not r:
            await query.edit_message_text("❌ Bulunamadı.")
            return
        old = r["remind_at"] if isinstance(r["remind_at"], datetime) else datetime.fromisoformat(r["remind_at"])
        if old.tzinfo is None:
            old = old.replace(tzinfo=tz)
        new = old + timedelta(days=days)
        db.snooze_reminder(rid, new, days_delayed=days)
        db.update_reminder(rid, escalation_count=0)  # Eskalasyonu sıfırla
        await query.edit_message_text(
            f"⏰ Ertelendi ({days}g): *{r['customer_name']}*\nYeni: {new.strftime('%d.%m.%Y %H:%M')}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # cancel:123
    m = re.match(r"^cancel:(\d+)$", data)
    if m:
        rid = int(m.group(1))
        r = db.get_reminder(rid)
        if not r:
            await query.edit_message_text("❌ Bulunamadı.")
            return
        db.mark_cancelled(rid)
        if r.get("apple_reminder_id"):
            apple_reminders.delete_reminder(r["apple_reminder_id"])
        await query.edit_message_text(
            f"❌ İptal: *{r['customer_name']}*", parse_mode=ParseMode.MARKDOWN,
        )
        return

    # undo:123 (geri al, tamamen sil)
    m = re.match(r"^undo:(\d+)$", data)
    if m:
        rid = int(m.group(1))
        r = db.get_reminder(rid)
        if not r:
            await query.edit_message_text("❌ Zaten silinmiş.")
            return
        if r.get("apple_reminder_id"):
            apple_reminders.delete_reminder(r["apple_reminder_id"])
        db.delete_reminder(rid)
        await query.edit_message_text(
            f"↩️ Geri alındı (#{rid} silindi). Yeniden anlat istersen.",
        )
        return

    # card:Ahmet
    m = re.match(r"^card:(.+)$", data)
    if m:
        name = m.group(1)
        await _show_card(query, name)
        return

    # ambiguous:customername:rid_placeholder veya benzeri (belirsiz isim seçimi)
    m = re.match(r"^pickcust:(\d+):(.+)$", data)
    if m:
        conv_chat_id = int(m.group(1))
        chosen_name = m.group(2)
        await _resolve_ambiguous_customer(query, conv_chat_id, chosen_name)
        return

    await query.answer("Bilinmeyen işlem")


async def _resolve_ambiguous_customer(query, chat_id: int, chosen_name: str):
    """Müşteri belirsizlik çözümü"""
    conv = db.get_conversation_state(chat_id)
    if not conv or conv["state"] != "awaiting_customer_pick":
        await query.edit_message_text("⏱️ Bu seçim artık geçerli değil.")
        return

    context_data = json.loads(conv["context_json"])
    parsed = context_data["parsed"]
    for k in ("due_date", "remind_at"):
        if parsed.get(k) and isinstance(parsed[k], str):
            parsed[k] = datetime.fromisoformat(parsed[k])

    parsed["customer_name"] = chosen_name
    db.clear_conversation_state(chat_id)

    warnings = db.get_smart_warnings(chosen_name)
    rid = save_reminder_and_sync(parsed, context_data.get("original_text", ""),
                                  context_data.get("audio_path", ""))

    msg = format_save_confirmation(rid, parsed, warnings)
    await query.edit_message_text(
        msg, parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_save_keyboard(rid),
    )


# ============================================================
# SES VE METİN
# ============================================================

@authorized
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice = update.message.voice or update.message.audio
    file_id = voice.file_id

    # v2.2: Duplicate kontrolü
    existing_rid = db.is_duplicate_voice(file_id, config.DUPLICATE_VOICE_WINDOW_MIN)
    if existing_rid:
        existing = db.get_reminder(existing_rid)
        if existing:
            await update.message.reply_text(
                f"⚠️ Aynı ses son {config.DUPLICATE_VOICE_WINDOW_MIN}dk içinde gönderildi.\n"
                f"Mevcut kayıt: `#{existing_rid}` *{existing['customer_name']}* — {existing['title']}",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

    await update.message.reply_text("🎧 Ses çevriliyor...")
    try:
        file = await context.bot.get_file(file_id)

        # v2.2: Ses arşivine kaydet
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = config.AUDIO_ARCHIVE_DIR / f"voice_{timestamp}_{file_id[:8]}.ogg"
        await file.download_to_drive(archive_path)

        text = await asyncio.to_thread(whisper_local.transcribe_audio, archive_path)
        if not text or len(text) < 3:
            await update.message.reply_text("⚠️ Ses anlaşılmadı, tekrar dene.")
            db.record_voice(file_id, update.effective_chat.id, None)
            return

        await update.message.reply_text(
            f"📝 *Çevrildi:*\n_{text}_\n\n🤖 İşleniyor...",
            parse_mode=ParseMode.MARKDOWN,
        )
        # process_text içinde reminder kaydedilince file_id ilişkilendir
        await process_text(update, text, audio_archive_path=str(archive_path),
                          voice_file_id=file_id)
    except Exception as e:
        logger.exception("Ses hatası")
        await update.message.reply_text(f"❌ {e}")


@authorized
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.effective_chat.id

    conv = db.get_conversation_state(chat_id)
    if conv and conv["state"] == "awaiting_clarification":
        await handle_clarification(update, text, conv)
        return

    await process_text(update, text)


async def _ask_customer_disambiguation(update, candidates: list, parsed: dict,
                                       original_text: str, audio_path: str = ""):
    """v2.1: Birden fazla yakın müşteri varsa kullanıcıya sor"""
    chat_id = update.effective_chat.id
    # Konuşma durumunu kaydet
    serializable = dict(parsed)
    for k in ("due_date", "remind_at"):
        if isinstance(serializable.get(k), datetime):
            serializable[k] = serializable[k].isoformat()

    db.set_conversation_state(
        chat_id, "awaiting_customer_pick",
        json.dumps({
            "parsed": serializable,
            "original_text": original_text,
            "audio_path": audio_path,
        }),
    )

    # Inline keyboard ile adayları sun
    buttons = []
    for cand, score in candidates[:5]:
        # callback_data sınırı 64 byte → kısalt
        name_short = cand["name"][:40]
        buttons.append([InlineKeyboardButton(
            f"👤 {cand['name'][:50]}" + (f"  ({cand.get('city', '')})" if cand.get('city') else ""),
            callback_data=f"pickcust:{chat_id}:{name_short}",
        )])
    # Hiçbiri seçeneği — yeni müşteri olarak ekle
    new_name = parsed.get("customer_name", "Bilinmiyor")[:40]
    buttons.append([InlineKeyboardButton(
        f"➕ Yeni: {new_name}",
        callback_data=f"pickcust:{chat_id}:{new_name}",
    )])

    await update.message.reply_text(
        f"🤔 Birden fazla müşteri eşleşti, hangisi?",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def process_text(update: Update, text: str, audio_archive_path: str = "",
                       voice_file_id: str = ""):
    try:
        parsed = await asyncio.to_thread(parser.parse_voice_text, text)
    except Exception as e:
        logger.exception("Parse hatası")
        await update.message.reply_text(
            f"⚠️ {e}", parse_mode=ParseMode.MARKDOWN,
        )
        return

    chat_id = update.effective_chat.id

    # SOHBET / GENEL SORU?
    if parsed.get("is_conversational"):
        await update.message.reply_text(
            parsed.get("chat_response"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # EKSİK BİLGİ?
    if parsed.get("needs_clarification"):
        question = parsed["needs_clarification"]["question"]
        serializable = dict(parsed)
        for k in ("due_date", "remind_at"):
            if isinstance(serializable.get(k), datetime):
                serializable[k] = serializable[k].isoformat()
        db.set_conversation_state(
            chat_id, "awaiting_clarification",
            json.dumps({
                "parsed": serializable,
                "original_text": text,
                "audio_path": audio_archive_path,
            }),
        )
        await update.message.reply_text(
            f"❓ {question}\n\n_İptal: /iptal yaz_",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # MÜŞTERİ BELİRSİZ Mİ?
    customer_query = parsed["customer_name"]
    candidates = db.find_customer_candidates(customer_query)
    # 2+ aday + skor farkı küçükse → sor
    if len(candidates) >= 2:
        score_diff = candidates[0][1] - candidates[1][1]
        if score_diff < config.CUSTOMER_AMBIGUITY_THRESHOLD and candidates[0][1] < 1.0:
            await _ask_customer_disambiguation(update, candidates, parsed, text, audio_archive_path)
            return

    # Tek aday varsa adı düzelt
    if candidates and candidates[0][1] >= 0.85:
        parsed["customer_name"] = candidates[0][0]["name"]

    # TEKRARLAYAN KURAL?
    if parsed.get("recurring"):
        rec = parsed["recurring"]
        rule_id = db.add_recurring(
            customer_name=parsed["customer_name"],
            title=parsed["title"],
            kind=parsed["kind"],
            amount=parsed.get("amount"),
            pattern=rec["pattern"],
            pattern_value=rec["value"],
            next_due=parsed["due_date"],
            reminder_hour=parsed["remind_at"].hour if parsed.get("remind_at") else 9,
            notes=parsed.get("notes", ""),
        )
        rid = save_reminder_and_sync(parsed, text, audio_archive_path)
        db.update_reminder(rid, recurring_id=rule_id)
        pattern_text = recurring.format_recurring_text(rec["pattern"], rec["value"])
        await update.message.reply_text(
            f"🔁 *Tekrarlayan kural #{rule_id}*\n{pattern_text}\n\n"
            f"İlk hatırlatma: #{rid} • {parsed['due_date'].strftime('%d.%m.%Y %H:%M')}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_save_keyboard(rid),
        )
        return

    # NORMAL
    warnings = db.get_smart_warnings(parsed["customer_name"])
    rid = save_reminder_and_sync(parsed, text, audio_archive_path)

    # v2.2: Ses kaydı varsa ledger'a yaz
    if voice_file_id:
        db.record_voice(voice_file_id, update.effective_chat.id, rid)

    await update.message.reply_text(
        format_save_confirmation(rid, parsed, warnings),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_save_keyboard(rid),
    )


async def handle_clarification(update, text: str, conv: dict):
    chat_id = update.effective_chat.id

    if text.lower().strip() in ("/iptal", "iptal", "vazgec", "vazgeç"):
        db.clear_conversation_state(chat_id)
        await update.message.reply_text("✅ İptal edildi.")
        return

    try:
        context_data = json.loads(conv["context_json"])
        parsed = context_data["parsed"]
        for k in ("due_date", "remind_at"):
            if parsed.get(k) and isinstance(parsed[k], str):
                parsed[k] = datetime.fromisoformat(parsed[k])

        updated = await asyncio.to_thread(parser.parse_clarification_answer, parsed, text)

        if updated.get("needs_clarification"):
            serializable = dict(updated)
            for k in ("due_date", "remind_at"):
                if isinstance(serializable.get(k), datetime):
                    serializable[k] = serializable[k].isoformat()
            db.set_conversation_state(
                chat_id, "awaiting_clarification",
                json.dumps({
                    "parsed": serializable,
                    "original_text": context_data["original_text"],
                    "audio_path": context_data.get("audio_path", ""),
                }),
            )
            await update.message.reply_text(
                f"❓ {updated['needs_clarification']['question']}",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        db.clear_conversation_state(chat_id)
        warnings = db.get_smart_warnings(updated["customer_name"])
        rid = save_reminder_and_sync(
            updated,
            context_data["original_text"],
            context_data.get("audio_path", ""),
        )
        await update.message.reply_text(
            format_save_confirmation(rid, updated, warnings),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_save_keyboard(rid),
        )
    except Exception as e:
        logger.exception("Clarification hatası")
        await update.message.reply_text(f"⚠️ {e}\n\nTekrar dene veya /iptal yaz.")


# ============================================================
# MAIN
# ============================================================

def main():
    # v2.2: Başlangıç doğrulaması
    config.print_validation_and_exit_if_errors()

    db.init_db()

    logger.info("Whisper ısıtılıyor...")
    whisper_local.get_model()

    if apple_reminders.is_available():
        apple_reminders.ensure_list_exists()

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Komutlar
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("version", cmd_version))
    app.add_handler(CommandHandler("durum", cmd_durum))
    app.add_handler(CommandHandler("liste", cmd_liste))
    app.add_handler(CommandHandler("bugun", cmd_bugun))
    app.add_handler(CommandHandler("yarin", cmd_yarin))
    app.add_handler(CommandHandler("hafta", cmd_hafta))
    app.add_handler(CommandHandler("kart", cmd_kart))
    app.add_handler(CommandHandler("musteri", cmd_musteri))
    app.add_handler(CommandHandler("risk", cmd_risk))
    app.add_handler(CommandHandler("musteriler", cmd_musteriler))
    app.add_handler(CommandHandler("riskli", cmd_riskli))
    # v2.2 yeni komutlar
    app.add_handler(CommandHandler("kasa", cmd_kasa))
    app.add_handler(CommandHandler(["dashboard", "panel"], cmd_dashboard))
    app.add_handler(CommandHandler(["istatistik", "stats"], cmd_istatistik))
    app.add_handler(CommandHandler("not", cmd_not))
    app.add_handler(CommandHandler("tekrarli", cmd_tekrarli))
    app.add_handler(CommandHandler("sablon", cmd_sablon))
    app.add_handler(CommandHandler(["disa_aktar", "export"], cmd_dis_aktar))
    app.add_handler(CommandHandler("yedek", cmd_yedek))

    # Callback handler (inline keyboard tıklamaları)
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Mesajlar
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Dinamik komut fallback
    app.add_handler(MessageHandler(filters.COMMAND, handle_dynamic_command))

    async def send_msg(chat_id, text, reply_markup=None):
        await app.bot.send_message(
            chat_id, text, parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True, reply_markup=reply_markup,
        )

    scheduler = ReminderScheduler(send_msg)

    async def on_startup(application):
        scheduler.start(config.AUTHORIZED_CHAT_IDS)
        logger.info("Bot hazır")

    async def on_shutdown(application):
        scheduler.stop()

    app.post_init = on_startup
    app.post_shutdown = on_shutdown

    logger.info("Bot başlatılıyor...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
