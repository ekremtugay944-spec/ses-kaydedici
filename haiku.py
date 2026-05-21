"""
Opsiyonel Anthropic Haiku entegrasyonu - v2.2
Varsayılan KAPALIDIR. .env'de USE_HAIKU=true yapılırsa devreye girer.

Ne yapar:
- Risk analizi: müşteri geçmişini Haiku'ya gönderip stratejik öneri al
- (İlerde) Müşteri belirsizliği çözümü

Maliyet: Ortalama 30 not/gün için ~$2-3/ay
"""
import logging
import json
from typing import Optional, List
from datetime import datetime
from config import (
    USE_HAIKU, ANTHROPIC_API_KEY, HAIKU_MODEL,
    HAIKU_USE_FOR_RISK_ANALYSIS,
)

logger = logging.getLogger(__name__)

_client = None


def is_enabled() -> bool:
    return USE_HAIKU and bool(ANTHROPIC_API_KEY)


def _get_client():
    """Anthropic client'ı lazy yükle"""
    global _client
    if _client is not None:
        return _client
    if not is_enabled():
        return None
    try:
        import anthropic
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        logger.info(f"Haiku aktif: {HAIKU_MODEL}")
        return _client
    except ImportError:
        logger.error("anthropic paketi yüklü değil. pip install anthropic")
        return None
    except Exception as e:
        logger.error(f"Haiku client hata: {e}")
        return None


def analyze_customer_risk(customer_name: str, summary: dict,
                          recent_history: List[dict],
                          new_amount: Optional[float] = None) -> Optional[str]:
    """
    Müşteri geçmişine bakarak akıllı risk yorumu yap.
    Dönüş: Türkçe 1-2 cümlelik strateji önerisi, veya None (kullanılamazsa)
    """
    if not HAIKU_USE_FOR_RISK_ANALYSIS:
        return None

    client = _get_client()
    if not client:
        return None

    try:
        # Geçmişi özetle
        history_summary = []
        for h in recent_history[:10]:
            due = h.get("due_date", "")
            if isinstance(due, datetime):
                due = due.strftime("%Y-%m-%d")
            status = h.get("status", "")
            kind = h.get("kind", "")
            amt = h.get("amount") or 0
            history_summary.append(f"- {due} {kind} {amt:,.0f}₺ → {status}")

        prompt = f"""Müşteri: {customer_name}
Toplam taahhüt: {summary.get('created_count', 0)}
Tamamlanan: {summary.get('done_count', 0)}
Ertelenen: {summary.get('delayed_count', 0)}
Açık alacak: {summary.get('open_amount', 0):,.0f}₺

Son hareketler:
{chr(10).join(history_summary) if history_summary else 'Yok'}

{f"Yeni taahhüt tutarı: {new_amount:,.0f}₺" if new_amount else ""}

Bu müşteriye yeni taahhüt vermeden önce kısaca (en fazla 2 cümle Türkçe) stratejik öneri:"""

        response = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error(f"Haiku risk analizi hata: {e}")
        return None
