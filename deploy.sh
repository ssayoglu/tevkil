#!/bin/bash
# ==============================================================================
# Telegram Avukat Tevkil Botu - Tek Komutla Otomatik VPS Kurulum Scripti
# ==============================================================================

set -e

echo "🚀 Tevkil Botu Otomatik Kurulumu Başlatılıyor..."

# 1. Temel Güncellemeler ve Gerekli Paketler
echo "📦 Sistem paketleri güncelleniyor..."
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl wget ufw

# 2. Docker & Docker Compose Kurulumu (Eğer yüklü değilse)
if ! command -v docker &> /dev/null; then
    echo "🐳 Docker kuruluyor..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER || true
    rm -f get-docker.sh
else
    echo "✅ Docker zaten yüklü."
fi

# 3. .env Dosyası Kontrolü
if [ ! -f .env ]; then
    echo "⚠️ .env dosyası bulunamadı, .env.example üzerinden oluşturuluyor..."
    cp .env.example .env
    echo "❗ Lütfen .env dosyasını BOT_TOKEN ve ADMIN_CHAT_ID bilgileriyle doldurun."
fi

# 4. Servislerin Başlatılması
echo "🏗️ Docker konteynerleri derlenip başlatılıyor..."
docker compose down || true
docker compose up -d --build

echo ""
echo "=============================================================================="
echo "🎉 TEVKİL BOTU BAŞARIYLA KURULDU VE BAŞLATILDI!"
echo "Logları canlı izlemek için: docker compose logs -f bot"
echo "=============================================================================="
