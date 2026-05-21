# 🎤 Gözde Plastik — Müşteri Hatırlatma Botu v2.2

> Sesli notlardan akıllı hatırlatma + müşteri hafızası + iPhone Reminders bildirimi
> **Tamamen yerel, sıfır API maliyeti, KVKK uyumlu**

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)]()
[![License](https://img.shields.io/badge/license-MIT-green.svg)]()
[![Version](https://img.shields.io/badge/version-2.2-orange.svg)]()

## ✨ Özellikler

- 🎤 Sesli not → otomatik hatırlatma (Whisper ile yerel)
- 🧠 Hibrit parser: dateparser (Türkçe) + Ollama (yapı) + fallback
- 📱 iPhone Reminders entegrasyonu (iki yönlü senkron, **tarih dahil**)
- 💬 Eksik bilgi için konuşma akışı
- 🔁 Tekrarlayan hatırlatmalar (aylık/haftalık/N-günlük)
- 👤 Müşteri kartları (telefon tıklanabilir, cep notu, risk skoru)
- 📊 **Dashboard** — anlık durum paneli (yeni)
- 💰 **Kasa** — bugün/hafta/ay tahsilat (yeni)
- 📈 **İstatistik** — bot kullanım metrikleri (yeni)
- 📝 **Cep notu** — `/not Ahmet 5 numarayı sevmiyor` (yeni)
- 🇹🇷 **Bayram/hafta sonu otomatik erteleme** (yeni, opsiyonel)
- 🌅 Sabah özeti (08:30) + 🌆 Akşam raporu (19:00)
- ⏰ Eskalasyon (2 saat sonra + ertesi gün tekrar)
- 🎙 Ses arşivi (30 gün, anlaşmazlık kanıtı)
- 🛡️ **Duplicate ses koruması** (yeni)
- 📲 Inline keyboard butonları
- ↩️ Geri al butonu
- 📋 Excel müşteri import/export
- 💾 DB yedeği indirme
- 💎 **Haiku opsiyonel** (varsayılan kapalı, isteyene açık)

## 🏗️ Mimari

```
🎤 Telegram'a ses
       ↓
  Duplicate kontrolü (5dk pencere)
       ↓
  Bot (Python)
       ↓
  faster-whisper (yerel, ~4s)
       ↓
  Hibrit parser:
   ├─ dateparser (Türkçe tarih)
   ├─ Ollama Qwen 2.5 (yapı, timeout=30s)
   └─ fallback (Ollama erişilemezse)
       ↓
   📅 Hafta sonu/bayram otomatik erteleme (opsiyonel)
       ↓
       ├─ 💾 SQLite WAL modu (eşzamanlı güvenli)
       └─ 🍎 macOS Reminders → iCloud → 📱 iPhone bildirim
       ↓
  APScheduler (8 iş):
   ├─ Vade kontrolü + eskalasyon (her dakika)
   ├─ iPhone senkron + TARİH SENKRON (5dk)
   ├─ Tekrarlayan materialize (00:05)
   ├─ Sabah özeti (08:30)
   ├─ Akşam raporu (19:00)
   ├─ Ses arşivi temizliği (03:00)
   ├─ Bekleyen konuşma temizliği (10dk)
   └─ Voice ledger temizliği (haftalık)
```

---

## 🚀 Kurulum (Mac Mini M4)

### 1. Sistem araçları

```bash
brew install python@3.12 ffmpeg git gh
brew install keith/formulae/reminders-cli  # iPhone Reminders için
```

Eğer `reminders-cli` kurulmazsa bot otomatik AppleScript fallback kullanır.

### 2. Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:7b
```

### 3. Proje

```bash
cd ~
unzip reminder-bot-v2.2.zip
cd reminder-bot-v2.2

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. `.env` ayarla

```bash
cp .env.example .env
nano .env
```

Minimum:
```env
TELEGRAM_BOT_TOKEN=7823456789:AAH...
AUTHORIZED_CHAT_IDS=123456789
```

### 5. Telegram Bot

1. [@BotFather](https://t.me/BotFather) → `/newbot`
2. Token al → `.env`'e yaz
3. Bota `/start` yaz
4. `https://api.telegram.org/bot<TOKEN>/getUpdates` → Chat ID'i bul, `.env`'e yaz

### 6. macOS Reminders İzinleri

İlk çalıştırma sırasında onay iste:
- **Sistem Ayarları → Gizlilik → Reminders → Terminal ✓**
- **Sistem Ayarları → iCloud → Reminders ✓**

### 7. Test

```bash
python bot.py
```

Eğer `.env` yanlışsa NET bir hata mesajı görürsün. Telegram'a:
- `/start`
- *"Ahmet Bey 25 Mayıs 5 bin lira ödeme"*

### 8. Auto-start

```bash
whoami  # kullanıcı adın
nano com.gozde.reminder-bot.plist  # "ekremtugay"'i değiştir

cp com.gozde.reminder-bot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.gozde.reminder-bot.plist
```

### 9. GitHub'a yükle

```bash
./setup-github.sh
```

Bu script seni adım adım yönlendirir, **private repo** oluşturur, push eder.

---

## 📖 Kullanım

### 🎤 Sesli Notlar

| Söylediğin | Bot ne yapar |
|---|---|
| *"Ahmet Bey 22 Kasım 15 bin lira"* | Net kayıt + iPhone bildirimi |
| *"Yarın sabah 8 Halil'in kamyonu"* | Saat dahil kayıt |
| *"Mehmet'i aradık tekrar arayacağız"* | Tarihi sorar |
| *"Her ayın 15'inde Halil bakiye"* | Tekrarlayan kural |
| *"Geçen Salı 3 bin aldık"* | Log mode (geçmiş kayıt) |
| *"Haftaya Salı"* | dateparser çözer |

### ⌨️ Komutlar

| Komut | Açıklama |
|---|---|
| `/help` | Tam liste |
| `/dashboard` | 📊 Anlık durum paneli |
| `/kasa` | 💰 Bugünkü tahsilat |
| `/kasa hafta` | 💰 Bu haftaki tahsilat |
| `/kasa ay` | 💰 Bu ayki tahsilat |
| `/liste` | Açık hatırlatmalar |
| `/bugun` `/yarin` `/hafta` | Zaman bazlı |
| `/kart <isim>` | Müşteri kartı |
| `/not Ahmet 5 numarayı sevmiyor` | 📝 Cep notu ekle |
| `/riskli` | En çok geciktiren müşteriler |
| `/tekrarli` | Tekrarlayan kurallar |
| `/sablon` `/dısa_aktar` | Excel import/export |
| `/yedek` | DB yedeği |
| `/istatistik` | Bot metrikleri |
| `/version` | Yapılandırma |

### 📲 Butonlar

Her hatırlatma altında:
- ✅ Tamamlandı
- ⏰ 1 / 3 gün ertele
- ❌ İptal
- 👤 Müşteri kartı

Yeni kayıt sonrası:
- ↩️ Yanlış anlaşıldı (geri al)

### 📝 Cep Notu

```
Sen: /not Ahmet eski model 5 numarayı sevmiyor
Bot: ✅ Ahmet için cep notu kaydedildi
```

Sonra Ahmet'le ilgili herhangi bir hatırlatma kaydederken:
```
✅ Kaydedildi #142
💵 Tutar: 25.000 ₺
📝 Müşteri notu: eski model 5 numarayı sevmiyor
```

### 🇹🇷 Hafta Sonu / Bayram Erteleme

`.env`:
```env
SKIP_WEEKENDS=true
SKIP_TURKEY_HOLIDAYS=true
```

Sonra *"30 Mayıs Halil ödeme"* dediğinde — 30 Mayıs Cumartesi, **otomatik 1 Haziran Pazartesi**'ye atılır.

### 💎 Haiku — Opsiyonel

Şu an **KAPALI**. Risk analizinde gerçek anlamlı strateji önerisi istiyorsan:

```env
USE_HAIKU=true
ANTHROPIC_API_KEY=sk-ant-...
HAIKU_USE_FOR_RISK_ANALYSIS=true
```

Aylık ek maliyet: **~80₺** (30 not/gün için)

---

## 🔧 Sorun Giderme

### Bot başlamıyor
v2.2 başlangıçta net mesaj verir:
```
[X] TELEGRAM_BOT_TOKEN ayarlanmamis!
   Cozum: .env dosyasini olustur (cp .env.example .env)
```

### Apple Reminders çalışmıyor
```bash
python -c "import apple_reminders; print(apple_reminders.get_backend())"
```
- `cli` → tamam
- `applescript` → fallback, çalışır
- `None` → izin yok, Sistem Ayarları → Gizlilik

### Ollama çöktü
v2.2 otomatik fallback'e geçer ve seni uyarır. `brew services restart ollama`.

### "DB kilitlendi" hatası
Artık olmaması lazım, WAL modu aktif. Hâlâ olursa `bot-stderr.log`'a bak.

---

## 💰 Maliyet

| | Aylık |
|---|---|
| Whisper (yerel) | 0 ₺ |
| Ollama (yerel) | 0 ₺ |
| Telegram | 0 ₺ |
| iPhone Reminders | 0 ₺ |
| GitHub Private | 0 ₺ |
| Mac Mini elektrik | ~50 ₺ |
| **Toplam** | **~50 ₺** |
| _Haiku opsiyonel ekleyince_ | _+~80 ₺_ |

## 🛣️ Yol Haritası

- [x] **v1.0** — Temel ses → hatırlatma
- [x] **v2.0** — Müşteri hafızası, iPhone Reminders, konuşma akışı
- [x] **v2.1** — Hibrit parser, eskalasyon, butonlar, ses arşivi
- [x] **v2.2** — Dashboard, kasa, duplicate koruma, WAL, Haiku hook, bayram erteleme
- [ ] **v3.0** — WhatsApp Business entegrasyonu
- [ ] **v3.1** — Paraşüt API ödeme senkronu
- [ ] **v3.2** — Web arayüzü (FastAPI + React)
- [ ] **v3.3** — Logo accounting bağlantısı

## 🔒 Veri Gizliliği

- ✅ Tüm veri Mac Mini'de
- ✅ Whisper YEREL
- ✅ Ollama YEREL
- ✅ SQLite YEREL
- 📤 İnternete giden: sadece Telegram + iCloud Reminders
- 💎 Haiku açıksa: SADECE müşteri adı + tutarlar (özet) gider, sesli not içeriği yerel kalır

## 📝 Lisans

MIT — bkz [LICENSE](LICENSE)
