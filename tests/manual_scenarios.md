# 🧪 Manuel Test Senaryoları — Gözde Plastik Reminder Bot

Bu doküman, Gözde Plastik Müşteri Hatırlatma Botunun farklı aşamalarındaki test senaryolarını ve el ile doğrulama adımlarını içerir.

---

## 🛠️ Faz 1: İskelet — Config & DB Testleri

### Test Senaryosu 1.1: `.env` Eksikliği Doğrulaması
* **Amaç:** Botun `.env` dosyası bulunmadığında veya `TELEGRAM_BOT_TOKEN` ayarlanmadığında güvenli bir şekilde çökmesini ve Ekrem Bey'e net bir çözüm önermesini doğrulamak.
* **Adımlar:**
  1. `/Users/primesports/Desktop/ses-kaydedici-crm/.env` dosyasını geçici olarak yeniden adlandırın (örn: `.env.backup`).
  2. Terminal üzerinden projeyi doğrulayan şu komutu koşturun:
     ```bash
     python3 -c "import config; config.print_validation_and_exit_if_errors()"
     ```
* **Beklenen Sonuç:** Komut çıkış kodu `1` olmalı ve ekrana şu hata mesajını yazdırmalıdır:
  `[X] TELEGRAM_BOT_TOKEN ayarlanmamis! Cozum: .env dosyasini olustur...`

### Test Senaryosu 1.2: Veritabanı ve WAL Modu Doğrulaması
* **Amaç:** Veritabanının oluşturulduğunu, tabloların eksiksiz yer aldığını ve WAL (Write-Ahead Logging) modunun aktif edildiğini doğrulamak.
* **Adımlar:**
  1. `.env` dosyasını geri getirin (içinde geçerli veya sahte bir token olsun).
  2. Terminal üzerinden veritabanını ilklendirin:
     ```bash
     python3 -c "import db; db.init_db(); print('DB Initialized')"
     ```
  3. SQLite3 CLI kullanarak WAL modunu doğrulayın:
     ```bash
     sqlite3 reminders.db "PRAGMA journal_mode;"
     ```
  4. Tabloların oluşturulduğunu doğrulayın:
     ```bash
     sqlite3 reminders.db ".tables"
     ```
* **Beklenen Sonuç:**
  - WAL sorgusu çıktı olarak `wal` dönmelidir.
  - Tablo sorgusu çıktı olarak `customers`, `reminders`, `recurring_rules`, `conversations`, `activity_log`, `voice_ledger`, `corrections` tablolarını listelemelidir.

---

## 🎤 Faz 2: Ses → Yazı & Parser Testleri

### Test Senaryosu 2.1: Türkçe Tarih Ön İşleme ve Ayrıştırma (dateparser)
* **Amaç:** `dateparser` entegrasyonumuzun Türkçe göreceli tarih ifadelerini milisaniyelik gecikmelerle doğru ayrıştırdığını doğrulamak.
* **Örnek Girdiler & Beklenen Sonuçlar:**
  - `"yarın"` → Yarının tarihi, varsayılan saat
  - `"haftaya Salı"` → Gelecek haftanın ilk Salı günü
  - `"ay sonu"` → İçinde bulunulan ayın son günü
  - `"ay başı"` → Önümüzdeki ayın 1. günü
  - `"ay ortası"` → Bu ayın 15'i veya önümüzdeki ayın 15'i
  - `"25 Mayıs"` → 25 Mayıs tarihi

---

## 🍎 Faz 3: Apple Reminders Testleri

### Test Senaryosu 3.1: AppleScript / CLI Fallback Doğrulaması
* **Amaç:** Sistemdeki Apple Reminders erişim yeteneklerini test etmek.
* **Adımlar:**
  1. Arka uç tespiti için:
     ```bash
     python3 -c "import apple_reminders; print('Backend:', apple_reminders.get_backend())"
     ```
* **Beklenen Sonuç:** Mac Mini üzerinde macOS Reminders izni varsa `cli` veya `applescript` çıktısı alınmalıdır.
