# 🤖 AGENT HANDOFF & PROJE GELİŞTİRME REHBERİ

> **Bu Belge Hakkında:** Bu dosya, projeyi başka bir bilgisayarda veya ortamda devralacak **AI Ajanı (Antigravity / Cursor / Claude / GPT vb.)** ve geliştirici meslektaşlarımız için hazırlanmıştır. Projenin tüm arka planını, şartname kurallarını, mimari kararları, mevcut kod durumunu ve yapılacak sonraki adımları içerir.

---

## 📌 1. Proje Özeti ve Amacı

Bu proje, **Av. Serkan SAYOĞLU** tarafından hazırlanan **17.02.2026** tarihli Teknik Şartname doğrultusunda geliştirilen bir **Telegram Avukat Tevkil Yönetim Botu**dur.

### Temel Hedef:
Telegram hukuk gruplarında paylaşılan tevkil ilanlarını otomatik olarak tespit etmek, başvuruları milisaniye hassasiyetli adil bir sıra sistemine sokmak, tarafları bot üzerinden gizlilik esasıyla (anonim) çift yönlü köprülemek (bridge), zaman aşımı ve ceza kurallarını işletmek ve tüm süreci yöneticilerin bulunduğu özel bir **Admin Denetim Grubu** üzerinden gözetim altında tutmaktır.

---

## 📜 2. Teknik Şartname ve İş Mantığı Kuralları

### A. İlan Takibi ve Başvuru
1. **Akıllı Filtre (`group_detector.py`):**
   - Hukuk grubunda paylaşılan mesajlarda `"tevkildir"` kelimesi aranır (Türkçe büyük/küçük harf, İ-I-ı-i varyasyonları ve Unicode normalizing yapılmıştır).
   - Bot, Telegram API kısıtı gereği başkasının mesajına buton ekleyemediğinden, tespit ettiği mesaja anında yanıt (reply) olarak **"📌 Tevkil İlanı Tespit Edildi"** mesajı ve `[📋 Başvur]` inline butonu gönderir.
2. **Canlı Şeffaf Başvuru Panosu (Özel Talep):**
   - Kullanıcılar butona tıkladıkça bot, gruptaki yanıt mesajını `HH:MM:SS.mmm` (milisaniye) hassasiyetiyle anlık olarak günceller (`edit_message_text`).
   - Örnek: `1. Av. Ahmet Y. — 14:32:15.120 [🟢 Görüşmede]`
   - Gruptaki herkes kimin kaçıncı salisede başvurduğunu şeffaf olarak görür.
3. **Milisaniye Sıralama Algoritması (`redis_queue.py`):**
   - Redis Sorted Set (`ZADD ... timestamp_ms`) ile atomik olarak kaydedilir (race condition engellenir).
   - **Sadece ilk tıklayan kişi (1. sıra)** görüşme başlatma hakkı kazanır.
   - Diğer adaylara: *"Tevkil için {X}. sıradasınız"* bilgisi iletilir.

### B. Anonim Köprüleme (Bridge) ve İletişim
1. **Gizlilik:** Tarafların Telegram profilleri/numaraları karşı tarafa gizlenir. Bot mesajları `[İlan Sahibi]` ve `[1. Sıra Başvuran Aday]` etiketleriyle iletir.
2. **Süreç Başlatma:**
   - İlan sahibine: *"Tevkil ilanı için 1. sıra başvurusu alındı. Lütfen görevin detaylarını yazarak iletişimi başlatın."* + `[🤝 Anlaştık]` / `[❌ Anlaşamadık]` butonları.
   - Adaya: *"Tevkil için 1. sıradan seçildiniz. İlan sahibi detayları ilettiğinde size buradan ulaştırılacaktır."*
3. **Medya / Dosya Desteği:** Sistem metin mesajlarının yanı sıra **fotoğraf** ve **PDF/doküman** gönderimini destekler.

### C. Zaman Aşımı (30 Dk Kuralı) ve Cezai Müeyyideler (`timeout_service.py`)
1. **30 Dakika Kuralı:** İlan sahibi eşleşme sağlandıktan sonra 30 dakika içinde ilk mesajı göndermezse ilan otomatik iptal edilir.
2. **Otomatik Kara Liste (Ban):** Kuralı ihlal eden ilan sahibi **5 gün süreyle kara listeye alınır** (yeni ilan veremez, başvuramaz).
3. **Grup Duyurusu:** İptal olan ilan ana grupta bot tarafından duyurulur.

### D. Admin Denetimi ve Loglama (`audit_service.py` & `admin_panel.py`)
1. **Merkezi İzleme:** Taraflar arasındaki tüm yazışmalar, fotoğraflar ve PDF'ler yöneticilerin bulunduğu özel **"Admin Denetim Grubu"**na anlık olarak aktarılır.
2. **Müdahale Komutları (Admin Grubunda Çalışır):**
   - `/durdur <ilan_id>`: Aktif görüşmeyi anında keser.
   - `/kullanici_kisitla <user_id> [gün] [sebep]`: Kullanıcıyı süreli kısıtlar.
   - `/ceza_kaldir <user_id>`: Kısıtlamayı kaldırır.
   - `/aktif_ilanlar`: Devam eden oturumları listeler.

### E. Anlaşma Teyit ve Sıra Devri Mekanizması (`confirmation.py`)
1. İlan sahibinin ekranındaki `[🤝 Anlaştık]` seçilirse ilan `COMPLETED` olur, taraflara teşekkür mesajı gider ve kapatılır.
2. `[❌ Anlaşamadık]` seçilirse sebep istenir: `[Ücret]`, `[Mesafe]`, `[Kıdem]`, `[Diğer]`.
3. **Önemli Kural:** Sebep **"Ücret" haricinde** seçilirse (Mesafe/Kıdem/Diğer), bot otomatik olarak sıradaki 2. adaya *"Sıra size geldi, kabul ediyor musunuz? [✅ Kabul] [❌ Red]"* teklifi gönderir. Kabul edilirse 2. adayla köprü kurulur.

---

## 🏗️ 3. Mimari ve Dizin Yapısı

```
.
├── Dockerfile                  # Bot container tanımı (Python 3.12-slim)
├── docker-compose.yml          # PostgreSQL 16, Redis 7 ve Bot orkestrasyonu
├── requirements.txt            # aiogram 3.x, sqlalchemy, asyncpg, redis, pydantic-settings
├── .env.example                # Örnek ortam değişkenleri
├── README.md                   # Genel proje dokümantasyonu
├── AGENT_HANDOFF.md            # Bu rehber (Ajan / Geliştirici devir kılavuzu)
├── docs/
│   ├── admin_guide.md          # Admin yönetim komutları ve panel dokümanı
│   └── deployment_guide.md     # Ubuntu VPS sunucu kurulum rehberi
├── bot/
│   ├── main.py                 # Bot başlatıcı, middleware ve router kayıtları
│   ├── config.py               # Pydantic Settings ortam değişkenleri
│   ├── database/
│   │   ├── connection.py       # Async SQLAlchemy session yöneticisi
│   │   └── models.py           # User, Listing, Application, BridgeSession, MessageLog modelleri
│   ├── services/
│   │   ├── redis_queue.py      # ZADD milisaniye sıralama ve lock mekanizması
│   │   ├── bridge_service.py   # Anonim DM mesaj/fotoğraf/PDF iletim motoru
│   │   ├── timeout_service.py  # 30 dk zamanlayıcı ve 5 gün otomatik ban servisi
│   │   └── audit_service.py    # Admin denetim grubuna anlık klonlama servisi
│   ├── handlers/
│   │   ├── group_detector.py   # 'tevkildir' filtresi ve ilan yakalama
│   │   ├── application.py      # 'Başvur' buton callback ve canlı pano güncellemesi
│   │   ├── bridge_chat.py      # İlan sahibi ve aday arasındaki DM mesajlaşması
│   │   ├── confirmation.py     # [Anlaştık] / [Anlaşamadık] / Sıra devri
│   │   └── admin_panel.py      # Admin müdahale komutları
│   └── middlewares/
│       ├── db_session.py       # Async SQLAlchemy session middleware
│       └── blacklist_check.py  # Kara liste ve ceza kontrol middleware
└── tests/
    ├── test_detector.py        # 'tevkildir' regex ve Türkçe karakter testleri
    └── test_queue_logic.py     # Milisaniye formatlama ve anlaşmazlık yönlendirme testleri
```

---

## 💻 4. Yeni Bilgisayarda Kurulum ve Çalıştırma

### 1. Depoyu Klonlayın ve Ortam Değişkenlerini Tanımlayın
```bash
git clone <REPO_URL>
cd <REPO_KLASORU>
cp .env.example .env
```

`.env` dosyasındaki kritik alanlar:
- `BOT_TOKEN`: Telegram `@BotFather`'dan alınan bot tokenı.
- `ADMIN_CHAT_ID`: Denetim grubunun chat ID'si (örn. `-1001234567890`).

### 2. Docker Compose ile Çalıştırma (Tavsiye Edilen)
```bash
docker compose up -d --build
```
Logları izlemek için:
```bash
docker compose logs -f bot
```

### 3. Yerel Geliştirme Ortamı (Local Python)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Testleri çalıştırmak için:
PYTHONPATH=. pytest tests/ -v
```

---

## 🎯 5. Gelecek Geliştirme Adımları (Roadmap / Backlog)

Projeyi devralacak ajan veya geliştirici için sıradaki potansiyel geliştirme görevleri:

1. **Canlı Telegram Testleri:**
   - Bir test grubunda botu admin yaparak `tevkildir` mesajı atmak.
   - İki farklı Telegram hesabıyla butona tıklayıp milisaniyeli sıralama panosunu ve DM köprüsünü test etmek.
   - Fotoğraf ve PDF gönderimi ile admin grubuna iletimini doğrulamak.
   - 30 dakika bekleme / zaman aşımı ve 5 günlük ban mekanizmasını tetiklemek.
2. **Baro Levha / TC Kimlik / Avukat Doğrulama (İsteğe Bağlı Ek Özellik):**
   - Başvuru yapan avukatların Baro Sicil No / Levha sorgulaması ile doğrulanması.
3. **Webhook Modu:**
   - Yüksek trafikli canlı sunucuda Polling yerine FastAPI / aiohttp tabanlı Telegram Webhook entegrasyonu.
4. **Admin Web Dashboard (İsteğe Bağlı):**
   - Adminlerin Telegram komutları dışında web tarayıcısı üzerinden tüm geçmiş logları, cezaları ve istatistikleri görebileceği hafif bir panel (FastAPI + Jinja2 / React).
