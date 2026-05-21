"""
SQLite veritabanı işlemleri - v2.2
Yenilikler:
- WAL modu (eşzamanlı erişim güvenli)
- voice_ledger tablosu (duplicate sesli not engelleme)
- corrections tablosu (kullanıcı düzeltmelerini öğren)
- Müşteri cep notu alanı
- Tahsilat istatistikleri (/kasa için)
"""
import sqlite3
import logging
import difflib
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from config import DB_PATH, CUSTOMER_FUZZY_THRESHOLD, CUSTOMER_AMBIGUITY_THRESHOLD

logger = logging.getLogger(__name__)


def get_conn():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # v2.2: WAL modu - eşzamanlı okuma+yazma için
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")  # WAL'a uygun
    return conn


def init_db():
    """Veritabanı tablolarını oluştur (+migrate)"""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                phone TEXT,
                company TEXT,
                address TEXT,
                city TEXT,
                tax_id TEXT,
                segment TEXT,
                notes TEXT,
                personal_note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER,
                customer_name TEXT NOT NULL,
                title TEXT NOT NULL,
                kind TEXT NOT NULL,
                amount REAL,
                due_date TIMESTAMP NOT NULL,
                remind_at TIMESTAMP NOT NULL,
                status TEXT DEFAULT 'open',
                original_voice_text TEXT,
                notes TEXT,
                apple_reminder_id TEXT,
                recurring_id INTEGER,
                audio_path TEXT,
                escalation_count INTEGER DEFAULT 0,
                last_notified_at TIMESTAMP,
                is_past_log INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS recurring_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                title TEXT NOT NULL,
                kind TEXT NOT NULL,
                amount REAL,
                pattern TEXT NOT NULL,
                pattern_value TEXT,
                next_due TIMESTAMP NOT NULL,
                reminder_hour INTEGER DEFAULT 9,
                active INTEGER DEFAULT 1,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                chat_id INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                context_json TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                reminder_id INTEGER,
                action TEXT NOT NULL,
                days_delayed INTEGER DEFAULT 0,
                amount REAL,
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # v2.2: Duplicate voice protection
        conn.execute("""
            CREATE TABLE IF NOT EXISTS voice_ledger (
                file_id TEXT PRIMARY KEY,
                chat_id INTEGER,
                reminder_id INTEGER,
                seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # v2.2: User corrections (parser eğitimi için, ilerde Haiku ile kullanılır)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_text TEXT,
                wrong_value TEXT,
                correct_value TEXT,
                field TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        _migrate(conn)

        # İndeksler
        conn.execute("CREATE INDEX IF NOT EXISTS idx_remind_at ON reminders(remind_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON reminders(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_customer ON reminders(customer_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_recurring_next ON recurring_rules(next_due, active)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_apple_rid ON reminders(apple_reminder_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_updated ON conversations(updated_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_voice_seen ON voice_ledger(seen_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_completed ON reminders(completed_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_log(created_at)")

    logger.info("Veritabanı hazır (WAL aktif)")


def _migrate(conn):
    """v2.1 → v2.2 migration"""
    # reminders kolonları
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(reminders)").fetchall()}
    additions = {
        "audio_path": "TEXT",
        "escalation_count": "INTEGER DEFAULT 0",
        "last_notified_at": "TIMESTAMP",
        "is_past_log": "INTEGER DEFAULT 0",
    }
    for col, ddl in additions.items():
        if col not in cols:
            try:
                conn.execute(f"ALTER TABLE reminders ADD COLUMN {col} {ddl}")
                logger.info(f"Migration: reminders.{col} eklendi")
            except sqlite3.OperationalError:
                pass

    # customers.personal_note
    cust_cols = {row["name"] for row in conn.execute("PRAGMA table_info(customers)").fetchall()}
    if "personal_note" not in cust_cols:
        try:
            conn.execute("ALTER TABLE customers ADD COLUMN personal_note TEXT")
            logger.info("Migration: customers.personal_note eklendi")
        except sqlite3.OperationalError:
            pass

    # activity_log.amount
    al_cols = {row["name"] for row in conn.execute("PRAGMA table_info(activity_log)").fetchall()}
    if "amount" not in al_cols:
        try:
            conn.execute("ALTER TABLE activity_log ADD COLUMN amount REAL")
            logger.info("Migration: activity_log.amount eklendi")
        except sqlite3.OperationalError:
            pass


# ============================================================
# DUPLICATE VOICE (v2.2)
# ============================================================

def is_duplicate_voice(file_id: str, window_min: int) -> Optional[int]:
    """
    Aynı ses dosyası son X dakikada görüldüyse, ilgili reminder_id'yi döndür.
    Yoksa None.
    """
    cutoff = datetime.now() - timedelta(minutes=window_min)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT reminder_id FROM voice_ledger WHERE file_id = ? AND seen_at >= ?",
            (file_id, cutoff),
        ).fetchone()
        return row["reminder_id"] if row else None


def record_voice(file_id: str, chat_id: int, reminder_id: Optional[int]):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO voice_ledger (file_id, chat_id, reminder_id, seen_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(file_id) DO UPDATE SET
                reminder_id = excluded.reminder_id,
                seen_at = excluded.seen_at
            """,
            (file_id, chat_id, reminder_id, datetime.now()),
        )


def cleanup_old_voice_ledger(days: int = 7):
    """7 günden eski file_id'leri temizle"""
    cutoff = datetime.now() - timedelta(days=days)
    with get_conn() as conn:
        result = conn.execute(
            "DELETE FROM voice_ledger WHERE seen_at < ?", (cutoff,)
        )
        if result.rowcount > 0:
            logger.info(f"{result.rowcount} eski voice_ledger kaydı silindi")


# ============================================================
# CORRECTIONS (v2.2)
# ============================================================

def record_correction(original_text: str, wrong: str, correct: str, field: str):
    """Kullanıcı düzeltmesini kaydet (ilerde parser eğitimi için)"""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO corrections (original_text, wrong_value, correct_value, field)
            VALUES (?, ?, ?, ?)
            """,
            (original_text, wrong, correct, field),
        )


def get_recent_corrections(field: str = None, limit: int = 20) -> list:
    with get_conn() as conn:
        if field:
            rows = conn.execute(
                "SELECT * FROM corrections WHERE field = ? ORDER BY created_at DESC LIMIT ?",
                (field, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM corrections ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


# ============================================================
# MÜŞTERİ İŞLEMLERİ
# ============================================================

def upsert_customer(name: str, **fields) -> int:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM customers WHERE name = ?", (name,)
        ).fetchone()
        allowed = {"phone", "company", "address", "city", "tax_id",
                   "segment", "notes", "personal_note"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if existing:
            customer_id = existing["id"]
            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
                conn.execute(
                    f"UPDATE customers SET {set_clause} WHERE id = ?",
                    list(updates.values()) + [customer_id],
                )
        else:
            cols = ["name"] + list(updates.keys())
            placeholders = ", ".join("?" * len(cols))
            cur = conn.execute(
                f"INSERT INTO customers ({', '.join(cols)}) VALUES ({placeholders})",
                [name] + list(updates.values()),
            )
            customer_id = cur.lastrowid
        return customer_id


def get_customer(name: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM customers WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None


def set_personal_note(customer_name: str, note: str):
    """Müşteri cep notunu güncelle (v2.2)"""
    with get_conn() as conn:
        upsert_customer(customer_name)
        conn.execute(
            "UPDATE customers SET personal_note = ? WHERE name = ?",
            (note, customer_name),
        )


def find_customer_candidates(query: str, threshold: float = None) -> List[Tuple[dict, float]]:
    threshold = threshold or CUSTOMER_FUZZY_THRESHOLD
    with get_conn() as conn:
        likes = conn.execute(
            "SELECT * FROM customers WHERE name LIKE ? OR company LIKE ?",
            (f"%{query}%", f"%{query}%"),
        ).fetchall()
        all_rows = conn.execute("SELECT * FROM customers").fetchall()

    candidates = []
    seen_ids = set()
    for r in likes:
        if r["id"] in seen_ids:
            continue
        if r["name"].lower() == query.lower():
            score = 1.0
        else:
            score = 0.95
        candidates.append((dict(r), score))
        seen_ids.add(r["id"])

    for r in all_rows:
        if r["id"] in seen_ids:
            continue
        ratio = difflib.SequenceMatcher(None, query.lower(), r["name"].lower()).ratio()
        if ratio >= threshold:
            candidates.append((dict(r), ratio))
            seen_ids.add(r["id"])

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates


def find_customer_fuzzy(query: str) -> Optional[dict]:
    candidates = find_customer_candidates(query)
    if candidates:
        return candidates[0][0]
    return None


def list_customers(limit: int = 100) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM customers ORDER BY name LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_customer_summary(customer_name: str) -> Optional[dict]:
    with get_conn() as conn:
        cust = conn.execute(
            "SELECT * FROM customers WHERE name = ?", (customer_name,)
        ).fetchone()
        if not cust:
            return None
        cust = dict(cust)

        stats_row = conn.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) as open_count,
                SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done_count,
                SUM(CASE WHEN status='open' AND kind='odeme' THEN amount ELSE 0 END) as open_amount,
                SUM(CASE WHEN status='done' AND kind='odeme' THEN amount ELSE 0 END) as collected_amount
            FROM reminders WHERE customer_name = ?
            """,
            (customer_name,),
        ).fetchone()

        risk_rows = conn.execute(
            "SELECT action, COUNT(*) as cnt FROM activity_log WHERE customer_name = ? GROUP BY action",
            (customer_name,),
        ).fetchall()
        risk = {r["action"]: r["cnt"] for r in risk_rows}

        cust.update({
            "total_reminders": stats_row["total"] or 0,
            "open_count": stats_row["open_count"] or 0,
            "done_count": stats_row["done_count"] or 0,
            "open_amount": stats_row["open_amount"] or 0,
            "collected_amount": stats_row["collected_amount"] or 0,
            "created_count": risk.get("created", 0),
            "delayed_count": risk.get("delayed", 0),
            "cancelled_count": risk.get("cancelled", 0),
        })
        return cust


# ============================================================
# HATIRLATMA İŞLEMLERİ
# ============================================================

def add_reminder(customer_name: str, title: str, kind: str,
                 due_date: datetime, remind_at: datetime,
                 amount: Optional[float] = None,
                 original_voice_text: str = "",
                 notes: str = "",
                 recurring_id: Optional[int] = None,
                 apple_reminder_id: Optional[str] = None,
                 audio_path: Optional[str] = None,
                 is_past_log: bool = False) -> int:
    with get_conn() as conn:
        customer_id = upsert_customer(customer_name)
        cur = conn.execute(
            """
            INSERT INTO reminders
            (customer_id, customer_name, title, kind, amount, due_date,
             remind_at, original_voice_text, notes, recurring_id,
             apple_reminder_id, audio_path, is_past_log)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (customer_id, customer_name, title, kind, amount, due_date,
             remind_at, original_voice_text, notes, recurring_id,
             apple_reminder_id, audio_path, 1 if is_past_log else 0),
        )
        rid = cur.lastrowid
        conn.execute(
            "INSERT INTO activity_log (customer_name, reminder_id, action, amount) VALUES (?, ?, 'created', ?)",
            (customer_name, rid, amount),
        )
        conn.execute(
            "UPDATE customers SET last_activity = ? WHERE id = ?",
            (datetime.now(), customer_id),
        )
        return rid


def get_reminder(reminder_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
        return dict(row) if row else None


def get_open_reminders(limit: int = 100) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE status = 'open' AND is_past_log = 0 ORDER BY remind_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_due_reminders(now: datetime) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE status = 'open' AND is_past_log = 0 AND remind_at <= ? ORDER BY remind_at ASC",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_reminders_between(start: datetime, end: datetime) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE status = 'open' AND is_past_log = 0 AND remind_at BETWEEN ? AND ? ORDER BY remind_at ASC",
            (start, end),
        ).fetchall()
        return [dict(r) for r in rows]


def get_customer_history(customer_name: str, limit: int = 50) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE customer_name LIKE ? ORDER BY created_at DESC LIMIT ?",
            (f"%{customer_name}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_done(reminder_id: int, note: str = ""):
    with get_conn() as conn:
        r = conn.execute(
            "SELECT customer_name, amount, kind FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
        if not r:
            return
        conn.execute(
            "UPDATE reminders SET status = 'done', completed_at = ? WHERE id = ?",
            (datetime.now(), reminder_id),
        )
        # Ödeme ise tahsilat olarak işaretle
        action = "collected" if r["kind"] == "odeme" else "completed"
        conn.execute(
            "INSERT INTO activity_log (customer_name, reminder_id, action, amount, note) VALUES (?, ?, ?, ?, ?)",
            (r["customer_name"], reminder_id, action, r["amount"], note),
        )


def mark_cancelled(reminder_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE reminders SET status = 'cancelled' WHERE id = ?", (reminder_id,))
        r = conn.execute(
            "SELECT customer_name FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
        if r:
            conn.execute(
                "INSERT INTO activity_log (customer_name, reminder_id, action) VALUES (?, ?, 'cancelled')",
                (r["customer_name"], reminder_id),
            )


def delete_reminder(reminder_id: int):
    with get_conn() as conn:
        r = conn.execute(
            "SELECT customer_name, audio_path FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
        if not r:
            return None
        conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        conn.execute(
            "INSERT INTO activity_log (customer_name, action, note) VALUES (?, 'deleted', ?)",
            (r["customer_name"], f"#{reminder_id} silindi"),
        )
        return dict(r)


def snooze_reminder(reminder_id: int, new_remind_at: datetime, days_delayed: int = 0):
    with get_conn() as conn:
        conn.execute(
            "UPDATE reminders SET remind_at = ?, status = 'open' WHERE id = ?",
            (new_remind_at, reminder_id),
        )
        r = conn.execute(
            "SELECT customer_name FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
        if r:
            conn.execute(
                "INSERT INTO activity_log (customer_name, reminder_id, action, days_delayed) VALUES (?, ?, 'delayed', ?)",
                (r["customer_name"], reminder_id, days_delayed),
            )


def update_reminder(reminder_id: int, **fields):
    allowed = {"title", "kind", "amount", "due_date", "remind_at", "notes",
               "customer_name", "apple_reminder_id", "recurring_id",
               "escalation_count", "last_notified_at"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    with get_conn() as conn:
        conn.execute(
            f"UPDATE reminders SET {set_clause} WHERE id = ?",
            list(updates.values()) + [reminder_id],
        )


def get_reminder_by_apple_id(apple_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM reminders WHERE apple_reminder_id = ?", (apple_id,)
        ).fetchone()
        return dict(row) if row else None


def get_reminders_with_apple_id() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE apple_reminder_id IS NOT NULL AND apple_reminder_id != ''"
        ).fetchall()
        return [dict(r) for r in rows]


def clone_reminder(source_id: int, new_due_date: datetime, new_remind_at: datetime) -> Optional[int]:
    """v2.2: 'Aynısını tekrarla' - kaynak hatırlatmayı kopyala"""
    src = get_reminder(source_id)
    if not src:
        return None
    new_id = add_reminder(
        customer_name=src["customer_name"],
        title=src["title"],
        kind=src["kind"],
        amount=src.get("amount"),
        due_date=new_due_date,
        remind_at=new_remind_at,
        original_voice_text=src.get("original_voice_text", ""),
        notes=src.get("notes", "") or "",
    )
    return new_id


# ============================================================
# TEKRARLAYAN
# ============================================================

def add_recurring(customer_name: str, title: str, kind: str, pattern: str,
                  pattern_value: str, next_due: datetime,
                  amount: Optional[float] = None, reminder_hour: int = 9,
                  notes: str = "") -> int:
    with get_conn() as conn:
        upsert_customer(customer_name)
        cur = conn.execute(
            """
            INSERT INTO recurring_rules
            (customer_name, title, kind, amount, pattern, pattern_value, next_due, reminder_hour, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (customer_name, title, kind, amount, pattern, pattern_value,
             next_due, reminder_hour, notes),
        )
        return cur.lastrowid


def get_active_recurring() -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM recurring_rules WHERE active = 1 ORDER BY next_due ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_due_recurring(now: datetime) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM recurring_rules WHERE active = 1 AND next_due <= ?",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]


def update_recurring_next(rule_id: int, next_due: datetime):
    with get_conn() as conn:
        conn.execute(
            "UPDATE recurring_rules SET next_due = ? WHERE id = ?",
            (next_due, rule_id),
        )


def deactivate_recurring(rule_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE recurring_rules SET active = 0 WHERE id = ?", (rule_id,))


# ============================================================
# KONUŞMA DURUMU
# ============================================================

def set_conversation_state(chat_id: int, state: str, context_json: str = ""):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO conversations (chat_id, state, context_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                state = excluded.state,
                context_json = excluded.context_json,
                updated_at = excluded.updated_at
            """,
            (chat_id, state, context_json, datetime.now()),
        )


def get_conversation_state(chat_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return dict(row) if row else None


def clear_conversation_state(chat_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM conversations WHERE chat_id = ?", (chat_id,))


def cleanup_stale_conversations(timeout_min: int):
    cutoff = datetime.now() - timedelta(minutes=timeout_min)
    with get_conn() as conn:
        result = conn.execute(
            "DELETE FROM conversations WHERE updated_at < ?", (cutoff,)
        )
        if result.rowcount > 0:
            logger.info(f"{result.rowcount} eski konuşma temizlendi")


# ============================================================
# RİSK
# ============================================================

def get_customer_risk(customer_name: str) -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT action, COUNT(*) as cnt FROM activity_log WHERE customer_name = ? GROUP BY action",
            (customer_name,),
        ).fetchall()
        stats = {r["action"]: r["cnt"] for r in rows}
        return {
            "customer": customer_name,
            "created": stats.get("created", 0),
            "completed": stats.get("completed", 0) + stats.get("collected", 0),
            "delayed": stats.get("delayed", 0),
            "cancelled": stats.get("cancelled", 0),
        }


def get_top_risky_customers(limit: int = 10) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT customer_name,
                   SUM(CASE WHEN action='created' THEN 1 ELSE 0 END) as created,
                   SUM(CASE WHEN action='delayed' THEN 1 ELSE 0 END) as delayed,
                   SUM(CASE WHEN action IN ('completed','collected') THEN 1 ELSE 0 END) as completed
            FROM activity_log
            GROUP BY customer_name
            HAVING created >= 3
            ORDER BY (CAST(delayed AS REAL) / created) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# ============================================================
# AKILLI BAĞLAM
# ============================================================

def get_smart_warnings(customer_name: str) -> List[str]:
    warnings = []
    summary = get_customer_summary(customer_name)
    if not summary:
        return warnings

    created = summary["created_count"]
    delayed = summary["delayed_count"]
    if created >= 3:
        rate = (delayed / created * 100)
        if rate >= 40:
            warnings.append(
                f"⚠️ Bu müşteri son {created} taahhüdün {delayed}'ini geciktirdi (%{rate:.0f})"
            )

    if summary["open_amount"] and summary["open_amount"] > 50000:
        warnings.append(f"💸 Bu müşteride zaten {summary['open_amount']:,.0f}₺ açık alacak var")

    if summary.get("last_activity"):
        la = summary["last_activity"]
        if isinstance(la, str):
            la = datetime.fromisoformat(la)
        days = (datetime.now() - la.replace(tzinfo=None)).days
        if days > 90:
            warnings.append(f"📅 Bu müşteriyle son aktivitende {days} gün geçmiş")

    if summary.get("personal_note"):
        warnings.append(f"📝 Müşteri notu: {summary['personal_note']}")

    return warnings


# ============================================================
# AKŞAM KAPANIŞ
# ============================================================

def get_today_stats() -> dict:
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    with get_conn() as conn:
        completed = conn.execute(
            """
            SELECT customer_name, title, kind, amount
            FROM reminders
            WHERE status = 'done' AND completed_at BETWEEN ? AND ?
            """,
            (today_start, today_end),
        ).fetchall()

        still_open = conn.execute(
            """
            SELECT customer_name, title, kind, amount, remind_at
            FROM reminders
            WHERE status = 'open' AND is_past_log = 0 AND remind_at < ?
            """,
            (today_end,),
        ).fetchall()

    return {
        "completed": [dict(r) for r in completed],
        "still_open": [dict(r) for r in still_open],
    }


# ============================================================
# KASA / TAHSİLAT (v2.2)
# ============================================================

def get_cash_summary(period: str = "today") -> dict:
    """
    Tahsilat özeti.
    period: today | week | month
    """
    now = datetime.now()
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now - timedelta(days=1)

    with get_conn() as conn:
        # Tahsil edilenler
        collected = conn.execute(
            """
            SELECT customer_name, amount, completed_at, title
            FROM reminders
            WHERE kind = 'odeme' AND status = 'done'
              AND completed_at >= ?
              AND amount IS NOT NULL
            ORDER BY completed_at DESC
            """,
            (start,),
        ).fetchall()

        # Hâlâ açık olanlar
        open_payments = conn.execute(
            """
            SELECT customer_name, amount, due_date, title
            FROM reminders
            WHERE kind = 'odeme' AND status = 'open' AND is_past_log = 0
              AND amount IS NOT NULL
            ORDER BY due_date ASC
            """
        ).fetchall()

    return {
        "period": period,
        "start": start,
        "collected": [dict(r) for r in collected],
        "collected_total": sum(r["amount"] or 0 for r in collected),
        "open": [dict(r) for r in open_payments],
        "open_total": sum(r["amount"] or 0 for r in open_payments),
    }


# ============================================================
# DASHBOARD (v2.2)
# ============================================================

def get_dashboard_data() -> dict:
    """Genel durum özeti"""
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = today_start + timedelta(days=7)
    month_ago = now - timedelta(days=30)
    quarter_ago = now - timedelta(days=90)

    with get_conn() as conn:
        # Toplam açık alacak
        total_open = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as t, COUNT(*) as c FROM reminders WHERE kind='odeme' AND status='open' AND is_past_log=0 AND amount IS NOT NULL"
        ).fetchone()

        # Bu hafta vadesi gelen
        week_due = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) as t FROM reminders
            WHERE kind='odeme' AND status='open' AND is_past_log=0
              AND amount IS NOT NULL AND due_date BETWEEN ? AND ?
            """,
            (today_start, week_end),
        ).fetchone()

        # Vadesi geçmiş
        overdue = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) as t, COUNT(*) as c FROM reminders
            WHERE kind='odeme' AND status='open' AND is_past_log=0
              AND amount IS NOT NULL AND due_date < ?
            """,
            (today_start,),
        ).fetchone()

        # 90+ gün geçmiş
        critical_overdue = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) as t FROM reminders
            WHERE kind='odeme' AND status='open' AND is_past_log=0
              AND amount IS NOT NULL AND due_date < ?
            """,
            (quarter_ago,),
        ).fetchone()

        # Bu hafta yapılacaklar (her tür)
        week_count = conn.execute(
            """
            SELECT kind, COUNT(*) as c FROM reminders
            WHERE status='open' AND is_past_log=0
              AND remind_at BETWEEN ? AND ?
            GROUP BY kind
            """,
            (today_start, week_end),
        ).fetchall()

        # Riskli müşteri sayısı
        risky = conn.execute(
            """
            SELECT COUNT(*) as c FROM (
                SELECT customer_name,
                    SUM(CASE WHEN action='created' THEN 1 ELSE 0 END) as cr,
                    SUM(CASE WHEN action='delayed' THEN 1 ELSE 0 END) as dl
                FROM activity_log GROUP BY customer_name
                HAVING cr >= 3 AND (CAST(dl AS REAL) / cr) >= 0.5
            )
            """
        ).fetchone()

    return {
        "total_open_amount": total_open["t"] or 0,
        "total_open_count": total_open["c"] or 0,
        "this_week_amount": week_due["t"] or 0,
        "overdue_amount": overdue["t"] or 0,
        "overdue_count": overdue["c"] or 0,
        "critical_overdue_amount": critical_overdue["t"] or 0,
        "week_by_kind": {r["kind"]: r["c"] for r in week_count},
        "risky_customer_count": risky["c"] or 0,
    }


# ============================================================
# BOT İSTATİSTİKLERİ (v2.2)
# ============================================================

def get_bot_stats() -> dict:
    """Sistemin kendi istatistikleri"""
    with get_conn() as conn:
        total_voices = conn.execute("SELECT COUNT(*) as c FROM voice_ledger").fetchone()
        total_reminders = conn.execute("SELECT COUNT(*) as c FROM reminders").fetchone()
        active_reminders = conn.execute(
            "SELECT COUNT(*) as c FROM reminders WHERE status='open'"
        ).fetchone()
        completed = conn.execute(
            "SELECT COUNT(*) as c FROM reminders WHERE status='done'"
        ).fetchone()
        total_customers = conn.execute("SELECT COUNT(*) as c FROM customers").fetchone()
        recurring_count = conn.execute(
            "SELECT COUNT(*) as c FROM recurring_rules WHERE active=1"
        ).fetchone()
        first_record = conn.execute(
            "SELECT MIN(created_at) as t FROM activity_log"
        ).fetchone()

    return {
        "total_voices": total_voices["c"] or 0,
        "total_reminders": total_reminders["c"] or 0,
        "active_reminders": active_reminders["c"] or 0,
        "completed_reminders": completed["c"] or 0,
        "total_customers": total_customers["c"] or 0,
        "recurring_rules": recurring_count["c"] or 0,
        "first_record": first_record["t"],
    }
