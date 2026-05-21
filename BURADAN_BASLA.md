# 🚀 Antigravity Paketi — Gözde Plastik Reminder Bot

Bu zip, **Antigravity IDE'de aynı projeyi yeniden yapma deneyi** için hazırlanmıştır.

## 📂 Klasör Yapısı

```
antigravity-paket/
├── BURADAN_BASLA.md           ← şu an okuduğun dosya
├── antigravity-prompts/       ← Antigravity'ye verilecek dokümanlar
│   ├── MASTER_PROMPT.md       ← İLK BU KOPYALA, Antigravity'ye yapıştır
│   ├── SYSTEM_RULES.md        ← Sıkı kurallar (agent okuyacak)
│   ├── PROJECT_SPEC.md        ← Detaylı şartname
│   ├── PHASE_PLAN.md          ← 7 fazlı build planı
│   └── README_FOR_AGENT.md    ← Agent için klasör rehberi
└── reference/                 ← Claude'un yazdığı referans kod (v2.2)
    ├── bot.py, db.py, parser.py, ...
    ├── README.md, CHANGELOG.md
    └── requirements.txt
```

## 🎯 Senin Yapacakların (3 Adım)

### 1️⃣ Antigravity'yi Aç ve Yeni Proje Oluştur

- `antigravity.google`'dan indir (henüz indirmediysen)
- Yeni proje: **`gozde-reminder-bot-antigravity`**
- Tüm zip içeriğini bu proje köküne kopyala

Klasör yapısı şöyle olmalı:
```
gozde-reminder-bot-antigravity/
├── antigravity-prompts/
└── reference/
```

### 2️⃣ Model Seç + Planning Mode Aç

- **Model**: Gemini 3 Pro (Antigravity varsayılan) veya Claude Sonnet 4.6
- **Mode**: Planning Mode (Fast Mode değil!)

### 3️⃣ Master Prompt'u Yapıştır

`antigravity-prompts/MASTER_PROMPT.md` dosyasını aç.

İçindeki `<PROMPT>` ... `</PROMPT>` arasındaki tüm metni kopyala.

Antigravity Agent Manager'a yapıştır. **Submit.**

## 🎬 Sonra Ne Olacak?

1. **Agent dokümanları okur** (`SYSTEM_RULES.md`, `PROJECT_SPEC.md`, `PHASE_PLAN.md`, `reference/`)
2. **Discovery Report** artifact'ı üretir — referansı nasıl gördüğünü, hangi alternatifleri düşündüğünü
3. Sen Google Docs-style yorum bırakırsın
4. Agent **Implementation Plan** artifact'ı üretir
5. Sen onaylarsın
6. Agent **Faz 1**'i kodlamaya başlar
7. Her faz sonunda walkthrough → sen onay → sonraki faz

## 💡 İpuçları

### Agent yanlış yola sapıyorsa
**Inline comment bırak.** Örnek: *"PostgreSQL ekleme, SQLite yeter"* veya *"Bu çok karmaşık, basitleştir"*.

### Agent çok yavaşsa
Faz büyüklüğüne bak. Tek seferde tüm projeyi istersen 30dk+ sürer. Faz fazına git.

### Karşılaştırma yapmak için
Bittiğinde agent'ın final walkthrough'undaki **karşılaştırma tablosu**'na bak. Referans (Claude) vs senin (Antigravity) yan yana.

### `.env` doldurma
Agent kod yazar ama `.env`'i sen dolduracaksın. Bu güvenlik nedeniyle.

## 🚨 Önemli Hatırlatma

- Mac Mini'ye **agent doğrudan erişemez**. Test komutları senin elinde.
- **Telegram token'ı** Antigravity'ye verme. Kod yazılınca `.env`'e sen yazarsın.
- **GitHub credentials** verme. Bittiğinde `setup-github.sh` ile sen push edersin.

## 🎓 Bu Deney Neden Anlamlı?

İki AI sistem aynı problem üzerinde çalışıyor:
- **Claude (referans)**: Tek thread'de planlı, sohbet bazlı
- **Antigravity (yeni)**: Çoklu agent, asenkron, artifact-based

Hangisinin sana daha çok yardımcı olduğunu **kendin göreceksin**. Bu deneyim, sonraki projelerde hangi aracı seçeceğine yön verir.

---

**İyi şanslar! Sonuçları beklerken sabırlı ol — Antigravity Planning Mode düşünür, hızlı değildir ama derindir.**
