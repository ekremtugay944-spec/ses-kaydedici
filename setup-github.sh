#!/bin/bash
# ==============================================================================
# Gözde Plastik Reminder Bot - GitHub Kurulum ve Yükleme Betiği
# ==============================================================================
# Bu betik, projenizi güvenli bir şekilde yerel Git deposu olarak ilklendirir,
# hassas verilerin (.env, veritabanı, ses dosyaları) .gitignore ile korunduğunu
# doğrular ve kendi özel (private) GitHub deponuza yüklemeniz için rehberlik eder.

echo "=========================================================="
echo "🚀 Gözde Plastik Reminder Bot - GitHub Kurulumu Başlıyor"
echo "=========================================================="

# 1. Git kurulu mu kontrolü
if ! command -v git &> /dev/null; then
    echo "❌ HATA: Git bu sistemde kurulu değil."
    echo "Lütfen önce Mac'inize Git kurun (brew install git) veya Xcode CLI araçlarını yükleyin."
    exit 1
fi

# 2. Git deposu ilklendir
if [ ! -d ".git" ]; then
    echo "⚡ Git deposu ilklendiriliyor..."
    git init
    git branch -M main
else
    echo "ℹ️  Git deposu zaten mevcut."
fi

# 3. .gitignore dosyasının varlığı
if [ ! -f ".gitignore" ]; then
    echo "⚠️  UYARI: .gitignore bulunamadı! Güvenlik için oluşturuluyor..."
    cat << 'EOF' > .gitignore
.env
.env.*
*.db
*.db-journal
*.db-wal
*.db-shm
*.sqlite
*.sqlite3
audio/
voice_*.ogg
voice_*.mp3
voice_*.m4a
voice_*.wav
import/upload_*.xlsx
import/musteriler_export_*.xlsx
import/musteri_sablon.xlsx
backups/
*.backup
*.log
*.log.*
bot.log*
__pycache__/
*.py[cod]
venv/
env/
.venv/
.DS_Store
._*
.vscode/
.idea/
.cache/
models/
*.lock
EOF
    echo "✅ .gitignore oluşturuldu."
fi

# 4. Dosyaları sahneye (staging) ekle
echo "📦 Proje dosyaları Git sahnesine ekleniyor..."
git add .

# 5. Durumu kontrol et ve .env veya .db gibi hassas dosyaların eklenmediğinden emin ol
echo "🛡️ Güvenlik kontrolü yapılıyor..."
SENSITIVE_FILES=$(git status --porcelain | grep -E '\.env|\.db|\.db-wal|audio/voice_' | grep -E '^A|^M')

if [ ! -z "$SENSITIVE_FILES" ]; then
    echo "⚠️ UYARI: Hassas dosyalar Git sahnesine dahil edilmiş görünüyor:"
    echo "$SENSITIVE_FILES"
    echo "Depolama temizleniyor ve hassas dosyalar hariç tutuluyor..."
    git reset
    git add .gitignore
    git add *.py
    git add requirements.txt
    git add LICENSE
    git add BURADAN_BASLA.md
    git add *.plist
    git add tests/
    git add reference/
else
    echo "✅ Güvenlik Kontrolü Başarılı! Hassas dosyalar (şifreler, veritabanı, sesler) koruma altında."
fi

# 6. İlk commit'i yap
echo "📝 İlk versiyon commit ediliyor..."
git commit -m "İlk Commit: Gözde Plastik CRM Bot v2.2 - Üretim Hazır Altyapı"

echo ""
echo "=========================================================="
echo "🎉 LOKAL KURULUM TAMAMLANDI!"
echo "=========================================================="
echo ""
echo "Şimdi bu projeyi özel (private) bir GitHub deposuna yüklemek için:"
echo ""
echo "1️⃣  github.com sitesine girip giriş yapın."
echo "2️⃣  Sağ üstteki '+' butonuna basıp 'New repository' deyin."
echo "3️⃣  Repository name kısmına 'ses-kaydedici-crm' yazın."
echo "4️⃣  ⚠️ ÇOK ÖNEMLİ: Depo görünürlüğünü kesinlikle 'PRIVATE' (Özel) seçin."
echo "5️⃣  'Create repository' butonuna basın."
echo "6️⃣  Açılan sayfadaki '…or push an existing repository from the command line' başlığı altındaki komutları kopyalayıp terminalinizde çalıştırın. Genellikle şöyledir:"
echo ""
echo "    git remote add origin https://github.com/KULLANICI_ADINIZ/ses-kaydedici-crm.git"
echo "    git push -u origin main"
echo ""
echo "Betikten çıkılıyor. İyi çalışmalar! 🚀"
