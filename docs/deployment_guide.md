# Ubuntu Linux VPS Sunucu Kurulum Kılavuzu

Bu belge, Telegram Avukat Tevkil Botu'nun 7/24 kesintisiz çalışacak bir Linux VPS (Ubuntu 22.04 / 24.04 LTS) sunucusuna sıfırdan kurulumunu açıklar.

---

## 1. Sunucu Ön Hazırlığı

Sunucunuza SSH ile bağlandıktan sonra paket listelerini güncelleyin ve gerekli temel araçları yükleyin:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl wget ufw
```

---

## 2. Docker ve Docker Compose Kurulumu

Sistem PostgreSQL, Redis ve Botu izole konteynerler halinde çalıştırmak için Docker kullanır:

```bash
# Docker resmi kurulum scripti
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Docker'ı mevcut kullanıcı ile çalıştırma izni
sudo usermod -aG docker $USER
newgrp docker

# Compose versiyonunu doğrulayın
docker compose version
```

---

## 3. Projenin Sunucuya Çekilmesi ve Yapılandırma

```bash
# Projeyi klonlayın
git clone <PROJE_REPO_ADRESI> tevkil-bot
cd tevkil-bot

# .env dosyasını oluşturun
cp .env.example .env
nano .env
```

`.env` dosyasını aşağıdaki değişkenlerle doldurun:
```env
BOT_TOKEN=123456789:ABCDefGHIjkLMNoPQRsTUVwxyZ
ADMIN_CHAT_ID=-1001234567890

POSTGRES_USER=tevkil_user
POSTGRES_PASSWORD=guclu_bir_veritabani_sifresi
POSTGRES_DB=tevkil_db
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

REDIS_HOST=redis
REDIS_PORT=6379

TIMEOUT_MINUTES=30
BAN_DURATION_DAYS=5
TIMEZONE=Europe/Istanbul
```

> **Önemli İpucu:**
> - `BOT_TOKEN` değerini Telegram'da [@BotFather](https://t.me/BotFather) üzerinden alabilirsiniz.
> - `ADMIN_CHAT_ID` değerini tespit etmek için: Admin grubunuza [@userinfobot](https://t.me/userinfobot) veya [@RawDataBot](https://t.me/RawDataBot) ekleyip `chat id` değerini kopyalayabilirsiniz (Grup ID'leri genellikle `-100` ile başlar).

---

## 4. Botun Başlatılması (Tek Komut)

```bash
# Servisleri arka planda derleyip başlatın
docker compose up -d --build
```

Konteyner durumlarını kontrol edin:
```bash
docker compose ps
```

Canlı logları takip etmek için:
```bash
docker compose logs -f bot
```

---

## 5. Güncelleme ve Yeniden Başlatma

İleride koda güncelleme geldiğinde:
```bash
git pull
docker compose up -d --build
```

Servisleri durdurmak için:
```bash
docker compose down
```

---

## 6. Güvenlik ve Sunucu Yedekleme

- **UFW Güvenlik Duvarı:** Sadece SSH bağlantısına izin verin. PostgreSQL ve Redis dış internete kapalıdır (Docker ağı içinde güvenle haberleşir).
  ```bash
  sudo ufw allow ssh
  sudo ufw enable
  ```
- **Veritabanı Yedeği Alma:**
  ```bash
  docker exec -t tevkil_postgres pg_dump -U tevkil_user tevkil_db > yedek_$(date +%F).sql
  ```
