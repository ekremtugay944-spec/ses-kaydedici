# Sürüm Geçmişi

## v2.2 — 2026-05-21

### 🔴 Kritik Düzeltmeler
- **`.env` doğrulaması**: Başlangıçta token vb. yoksa açık hata mesajı + çıkış
- **SQLite WAL modu**: Eşzamanlı erişim sorunları çözüldü
- **Apple Reminders tarih senkronu**: iPhone'da tarih değişikliği DB'ye yansıyor
- **Ollama timeout + fallback**: Ollama yanıt vermezse primitif parser devreye girer

### 🟡 Önemli İyileştirmeler
- **Duplicate ses koruması**: Aynı sesli not 5dk içinde tekrar gelirse atlanır
- **Telegram mesaj parçalama**: 4096 karakter limiti aşılırsa otomatik parçalanır
- **Tıklanabilir telefon (`tel:`)**: Müşteri kartında mobilde tek tık arama

### 🟢 Yeni Komutlar
- **`/kasa`** — Bugün/hafta/ay tahsilat özeti
- **`/dashboard`** — Genel durum paneli (açık alacak, vadesi geçen, vb.)
- **`/istatistik`** — Bot kullanım istatistikleri
- **`/not <müşteri> <metin>`** — Müşteriye cep notu ekle

### 💎 Yeni Özellikler
- **Hafta sonu otomatik erteleme** (opsiyonel, `SKIP_WEEKENDS=true`)
- **Türkiye bayramları otomatik erteleme** (opsiyonel, `SKIP_TURKEY_HOLIDAYS=true`)
- **Müşteri cep notu** — kartta ve risk uyarılarında görünür
- **Haiku opsiyonel entegrasyonu** (varsayılan KAPALI, kullanıcı isterse açabilir)
- **Tahsilat takibi** — `mark_done` artık ödemeler için "collected" log atıyor
- **`corrections` tablosu** — Kullanıcı düzeltmeleri ileride parser eğitimi için

### 🛠️ Altyapı
- 8 zamanlanmış iş (önceki 7 + voice_ledger temizliği)
- `voice_ledger` tablosu (duplicate koruması)
- `corrections` tablosu (ilerideki AI eğitimi için)
- `customers.personal_note` alanı

## v2.1 — 2026-05-21
- Hibrit parser (dateparser + Ollama)
- İki yönlü Apple senkron
- Eskalasyon
- Inline keyboard
- Geri al butonu
- Ses arşivi
- Akşam raporu
- (Detay için git log)

## v2.0 — Müşteri hafızası, iPhone Reminders, konuşma akışı, tekrarlayanlar, Excel import

## v1.0 — Temel ses → hatırlatma sistemi
