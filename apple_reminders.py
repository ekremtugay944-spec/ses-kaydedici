"""
Apple Reminders entegrasyonu - v2.2
- Önce reminders-cli (hızlı)
- Yoksa AppleScript fallback (Xcode gerektirmez)
- İki yönlü senkron: tamamlama + silme + tarih değişikliği
- Async-friendly: Bloklamaları engellemek için asyncio.to_thread ile koşturulmaya uygundur.
"""
import subprocess
import logging
import json
import re
from datetime import datetime
from typing import Optional, List, Dict
from config import (
    APPLE_REMINDERS_ENABLED, APPLE_REMINDERS_CLI, APPLE_REMINDERS_LIST,
    APPLE_USE_APPLESCRIPT_FALLBACK,
)

logger = logging.getLogger(__name__)

_backend = None  # "cli", "applescript", or None


def _detect_backend() -> Optional[str]:
    if not APPLE_REMINDERS_ENABLED:
        logger.info("Apple Reminders pasif (.env veya config üzerinden)")
        return None

    # 1. CLI dene
    try:
        result = subprocess.run(
            [APPLE_REMINDERS_CLI, "show-lists"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            logger.info("Apple Reminders backend: CLI")
            return "cli"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 2. AppleScript fallback
    if APPLE_USE_APPLESCRIPT_FALLBACK:
        try:
            result = subprocess.run(
                ["osascript", "-e", 'tell application "Reminders" to get name of first list'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                logger.info("Apple Reminders backend: AppleScript")
                return "applescript"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    logger.warning("Apple Reminders kullanılamıyor")
    return None


def get_backend() -> Optional[str]:
    global _backend
    if _backend is None:
        _backend = _detect_backend()
    return _backend


def is_available() -> bool:
    return get_backend() is not None


# ============================================================
# CLI BACKEND
# ============================================================

def _cli_ensure_list():
    try:
        result = subprocess.run(
            [APPLE_REMINDERS_CLI, "show-lists"],
            capture_output=True, text=True, timeout=5,
        )
        if APPLE_REMINDERS_LIST not in result.stdout:
            subprocess.run(
                [APPLE_REMINDERS_CLI, "new-list", APPLE_REMINDERS_LIST],
                capture_output=True, text=True, timeout=5,
            )
            logger.info(f"Liste oluşturuldu: {APPLE_REMINDERS_LIST}")
    except Exception as e:
        logger.error(f"CLI ensure_list hatası: {e}")


def _cli_add(title: str, due: datetime, notes: str) -> Optional[str]:
    _cli_ensure_list()
    cmd = [
        APPLE_REMINDERS_CLI, "add", APPLE_REMINDERS_LIST, title,
        "--due-date", due.strftime("%Y-%m-%d %H:%M:%S"),
        "--format", "json",
    ]
    if notes:
        cmd.extend(["--notes", notes])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            logger.error(f"CLI add: {result.stderr}")
            return None
        try:
            data = json.loads(result.stdout.strip())
            return data.get("externalId") or data.get("id")
        except json.JSONDecodeError:
            return _cli_find_by_title(title)
    except Exception as e:
        logger.error(f"CLI add exception: {e}")
        return None


def _cli_find_by_title(title: str) -> Optional[str]:
    try:
        result = subprocess.run(
            [APPLE_REMINDERS_CLI, "show", APPLE_REMINDERS_LIST, "--format", "json"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        for item in data:
            if item.get("title") == title and not item.get("isCompleted"):
                return item.get("externalId") or item.get("id")
    except Exception:
        pass
    return None


def _cli_complete(reminder_id: str) -> bool:
    try:
        result = subprocess.run(
            [APPLE_REMINDERS_CLI, "complete", APPLE_REMINDERS_LIST, reminder_id],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _cli_delete(reminder_id: str) -> bool:
    try:
        result = subprocess.run(
            [APPLE_REMINDERS_CLI, "delete", APPLE_REMINDERS_LIST, reminder_id],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _cli_list_all() -> List[Dict]:
    """Tüm öğeleri (tamamlanmış + bekleyen) listele - tarih dahil"""
    items = []
    try:
        # Bekleyenler
        r1 = subprocess.run(
            [APPLE_REMINDERS_CLI, "show", APPLE_REMINDERS_LIST, "--format", "json"],
            capture_output=True, text=True, timeout=5,
        )
        if r1.returncode == 0:
            for item in json.loads(r1.stdout):
                item["_completed"] = False
                items.append(item)
        # Tamamlananlar
        r2 = subprocess.run(
            [APPLE_REMINDERS_CLI, "show", APPLE_REMINDERS_LIST,
             "--only-completed", "--format", "json"],
            capture_output=True, text=True, timeout=5,
        )
        if r2.returncode == 0:
            for item in json.loads(r2.stdout):
                item["_completed"] = True
                items.append(item)
    except Exception as e:
        logger.error(f"CLI list hatası: {e}")
    return items


# ============================================================
# APPLESCRIPT BACKEND
# ============================================================

def _osascript(script: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        logger.error(f"AppleScript: {result.stderr}")
    except Exception as e:
        logger.error(f"osascript hatası: {e}")
    return None


def _as_ensure_list():
    script = f'''
    tell application "Reminders"
        if not (exists list "{APPLE_REMINDERS_LIST}") then
            make new list with properties {{name:"{APPLE_REMINDERS_LIST}"}}
        end if
    end tell
    '''
    _osascript(script)


def _as_add(title: str, due: datetime, notes: str) -> Optional[str]:
    _as_ensure_list()
    # AppleScript için tarihi formatla
    due_str = due.strftime("%m/%d/%Y %H:%M:%S")
    safe_title = title.replace('"', '\\"')
    safe_notes = (notes or "").replace('"', '\\"').replace("\n", " ")

    script = f'''
    tell application "Reminders"
        set theDate to date "{due_str}"
        set newRem to make new reminder at list "{APPLE_REMINDERS_LIST}" with properties {{name:"{safe_title}", remind me date:theDate, body:"{safe_notes}"}}
        return id of newRem
    end tell
    '''
    rid = _osascript(script)
    if rid:
        # AppleScript "x-coredata://..." formatında ID döner
        return rid
    return None


def _as_complete(reminder_id: str) -> bool:
    script = f'''
    tell application "Reminders"
        try
            set targetRem to first reminder whose id is "{reminder_id}"
            set completed of targetRem to true
            return "ok"
        on error
            return "notfound"
        end try
    end tell
    '''
    return _osascript(script) == "ok"


def _as_delete(reminder_id: str) -> bool:
    script = f'''
    tell application "Reminders"
        try
            delete (first reminder whose id is "{reminder_id}")
            return "ok"
        on error
            return "notfound"
        end try
    end tell
    '''
    return _osascript(script) == "ok"


def _as_list_all() -> List[Dict]:
    """AppleScript ile liste oku"""
    script = f'''
    tell application "Reminders"
        set theList to list "{APPLE_REMINDERS_LIST}"
        set output to ""
        repeat with rem in (reminders of theList)
            set output to output & (id of rem) & "|||" & (name of rem) & "|||" & (completed of rem as text) & "###"
        end repeat
        return output
    end tell
    '''
    raw = _osascript(script)
    if not raw:
        return []

    items = []
    for chunk in raw.split("###"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split("|||")
        if len(parts) >= 3:
            items.append({
                "externalId": parts[0],
                "title": parts[1],
                "_completed": parts[2].strip().lower() == "true",
            })
    return items


# ============================================================
# PUBLIC API (backend agnostic)
# ============================================================

def ensure_list_exists():
    backend = get_backend()
    if backend == "cli":
        _cli_ensure_list()
    elif backend == "applescript":
        _as_ensure_list()


def add_reminder(title: str, due_date: datetime, notes: str = "") -> Optional[str]:
    backend = get_backend()
    if backend == "cli":
        return _cli_add(title, due_date, notes)
    if backend == "applescript":
        return _as_add(title, due_date, notes)
    return None


def complete_reminder(reminder_id: str) -> bool:
    if not reminder_id:
        return False
    backend = get_backend()
    if backend == "cli":
        return _cli_complete(reminder_id)
    if backend == "applescript":
        return _as_complete(reminder_id)
    return False


def delete_reminder(reminder_id: str) -> bool:
    if not reminder_id:
        return False
    backend = get_backend()
    if backend == "cli":
        return _cli_delete(reminder_id)
    if backend == "applescript":
        return _as_delete(reminder_id)
    return False


def list_all_reminders() -> List[Dict]:
    """Tüm hatırlatıcıları çek"""
    backend = get_backend()
    if backend == "cli":
        return _cli_list_all()
    if backend == "applescript":
        return _as_list_all()
    return []


def get_two_way_sync_state() -> Dict[str, Dict]:
    """
    Apple'daki tüm öğelerin durumunu döndür: {apple_id: {completed, title, due_date}}
    Tarih senkronu için due_date de dahil.
    """
    items = list_all_reminders()
    result = {}
    for item in items:
        aid = item.get("externalId")
        if not aid:
            continue

        # Tarih bilgisini parse et
        due_date = None
        # reminders-cli: 'dueDate' veya 'date' alanı olabilir
        for date_key in ("dueDate", "remindMeDate", "date"):
            if date_key in item and item[date_key]:
                try:
                    raw = item[date_key]
                    if isinstance(raw, str):
                        # ISO 8601 dene
                        due_date = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    elif isinstance(raw, (int, float)):
                        due_date = datetime.fromtimestamp(raw)
                    break
                except (ValueError, TypeError):
                    pass

        result[aid] = {
            "completed": item.get("_completed", False),
            "title": item.get("title", ""),
            "due_date": due_date,
        }
    return result


def update_reminder_date(reminder_id: str, new_due: datetime) -> bool:
    """Apple Reminders'taki tarihi güncelle (bot tarafından erteleme)"""
    if not reminder_id:
        return False
    backend = get_backend()

    if backend == "cli":
        # CLI'da edit komutu yok, sil-ekle gerekir, atla
        return False

    if backend == "applescript":
        due_str = new_due.strftime("%m/%d/%Y %H:%M:%S")
        script = f'''
        tell application "Reminders"
            try
                set targetRem to first reminder whose id is "{reminder_id}"
                set remind me date of targetRem to date "{due_str}"
                return "ok"
            on error
                return "notfound"
            end try
        end tell
        '''
        return _osascript(script) == "ok"

    return False
