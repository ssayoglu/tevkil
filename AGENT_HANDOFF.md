# 🤖 AGENT HANDOFF & PROJE GELİŞTİRME REHBERİ

> **Bu Belge Hakkında:** Bu dosya, projeyi devralacak olan **AI Ajanı (Antigravity / Cursor / Claude / GPT vb.)** ve yazılımcı meslektaşlarımız için hazırlanmıştır. Projenin mimarisini, şartname kurallarını, canlı sunucu bilgilerini, son yapılan kritik güncellemeleri ve karşılaşılan özel durumları (edge-cases) eksiksiz olarak aktarır.

---

## 📌 1. Proje Özeti ve Temel Amacı

Bu sistem, **Av. Serkan SAYOĞLU** tarafından hazırlanan şartname doğrultusunda geliştirilmiş profesyonel bir **Telegram Avukat Tevkil Yönetim Botu**dur.

### Temel Hedefler:
1. **İlan Takibi:** Telegram hukuk gruplarındaki tevkil taleplerini (`tevkildir`, tüm il/ilçe adliyeleri ve duruşma/görev kelimeleri) otomatik tespit etmek.
2. **Anti-Bypass Koruması:** İlan sahibine harici DM atılmasını engellemek amacıyla orijinal mesajı silip bot üzerinden anonim yayınlamak.
3. **Milisaniye Sıralama:** Başvuran adayları Redis Sorted Set ile milisaniye hassasiyetinde kuyruğa sokmak.
4. **Anonim Köprüleme (Bridge):** İlan sahibi ile 1. sıradaki adayı kimliklerini/telefonlarını gizleyerek bot üzerinden mesaj, fotoğraf, ses kaydı ve PDF formatında konuşturmak.
5. **Rank, Handikap & Ceza Mekanizması:**
   - Başarılı görevde +5 Rank puanı.
   - 30 dakika yanıtsızlıkta +20 Ceza puanı & 5 gün ban.
   - Tarife altı teklifte +30 Ceza puanı & 15 gün Direkt Ban (ve ana grupta duyuru).
   - Ceza puanı olanlara başvuruda kademeli sanal gecikme (handikap).
6. **Yönetim Denetimi:** Tüm süreci özel bir Admin Denetim Grubu üzerinden thread/konu bazlı izlemek ve tek dokunuşla tüm mesaj loglarını görebilmek.
7. **Baro Doğrulama:** Grupta mesaj yazan üyelerin Baro ve Sicil doğrulamalarını yapmak, doğrulanmamış kullanıcıların uygunsuz mesaj atmasını engellemek.

---

## 🌐 2. Canlı Sunucu ve Ortam Bilgileri

- **Sunucu IP:** `185.247.136.120` (Ubuntu VPS)
- **Kullanıcı:** `root`
- **Proje Dizini:** `/root/tevkil`
- **Çalışma Modu:** Docker Compose (`tevkil_bot`, `tevkil_postgres`, `tevkil_redis`)
- **Git Branch:** `main` (origin: GitHub)
- **Veritabanı:** PostgreSQL 16 (`tevkil_db`)
- **Cache/Queue:** Redis 7

### Kritik ID Tanımları:
- **Tevkil Ana Test Süpergrubu:** `-1004451880964`
- **Admin Denetim Grubu:** `-5417865581`
- **Sistem Admin ID'leri:** `750634330`, `5689717384`

### Canlı Sunucu Komutları:
```bash
# Canlı logları izleme
ssh root@185.247.136.120 "docker logs -f --tail 100 tevkil_bot"

# Güncelleme ve yeniden başlatma
ssh root@185.247.136.120 "cd /root/tevkil && git pull && docker compose restart bot"
```

---

## 🏗️ 3. Mimari ve Dizin Yapısı

```
.
├── Dockerfile                  # Python 3.12-slim tabanlı imaj
├── docker-compose.yml          # PostgreSQL 16, Redis 7 ve Bot orkestrasyonu
├── deploy.sh                   # VPS kurulum scripti
├── requirements.txt            # aiogram 3.x, sqlalchemy, asyncpg, redis, pydantic-settings
├── AGENT_HANDOFF.md            # Bu rehber
├── README.md                   # Genel dokümantasyon
├── docs/
│   ├── admin_guide.md          # Admin komutları ve panel kullanım kılavuzu
│   └── deployment_guide.md     # VPS kurulum rehberi
├── bot/
│   ├── main.py                 # Bot başlatıcı, checker loopları ve router kayıtları
│   ├── config.py               # Pydantic Settings ortam değişkenleri
│   ├── database/
│   │   ├── connection.py       # Async SQLAlchemy session yöneticisi
│   │   └── models.py           # User, Listing, Application, BridgeSession, MessageLog, PenaltyLog
│   ├── services/
│   │   ├── redis_queue.py      # ZADD milisaniye kuyruğu, admin listing thread id takibi
│   │   ├── rank_service.py     # Rank, ceza puanı ve kademeli handikap hesaplama
│   │   ├── baro_service.py     # Baro sicil doğrulama ve il eşleme
│   │   ├── bridge_service.py   # Anonim DM mesaj iletimi (metin/medya/ses/evrak)
│   │   ├── timeout_service.py  # 30 dk kuralı ve dirençli arka plan denetleyicisi
│   │   └── audit_service.py    # Admin denetim grubuna loglama ve thread gruplama
│   ├── handlers/
│   │   ├── user_panel.py       # /start, /yardim, /profilim, /ilanlarim, rehber ve butonlar
│   │   ├── group_detector.py   # Akıllı adliye NLP filtresi ve ilan yakalama
│   │   ├── application.py      # [Başvur] / [Görevlendirmeye Git] ve canlı pano
│   │   ├── bridge_chat.py      # Anonim köprü DM sohbeti
│   │   ├── confirmation.py     # [Anlaştık] / [Anlaşamadık] / Tarife Ban / Devir
│   │   └── admin_panel.py      # Admin müdahale, istatistik, ceza ve test sıfırlama
│   ├── middlewares/
│   │   ├── db_session.py       # Async DB session middleware
│   │   ├── blacklist_check.py  # Yasaklı kullanıcı kontrolü
│   │   └── baro_check.py       # Baro doğrulama middleware'i (mesaj kontrolü)
│   └── utils/
│       ├── courthouses.py      # 81 il + tüm ilçe adliyeleri veri seti
│       └── time_utils.py       # Europe/Istanbul saat ve milisaniye formatlayıcı
└── tests/
    ├── test_detector.py
    ├── test_queue_logic.py
    ├── test_rank_service.py
    ├── test_baro_service.py
    ├── test_time_utils.py
    ├── test_handlers_user_panel.py
    ├── test_handlers_admin.py
    └── test_confirmation_chain.py
```

---

## ⚡ 4. Son Eklenen Kritik Özellikler ve Çözülen Problemler (Önemli!)

Yeni devralacak ajanların bilmesi gereken en son mimari düzenlemeler:

### 1. Telegram Yazma Kilidi Hatası ve Çözümü (`baro_check.py`)
- **Eski Durum:** Bot, doğrulanmamış kullanıcıları Telegram API üzerinden `restrict_chat_member(can_send_messages=False)` ile susturuyordu. Bu durum kullanıcının Telegram uygulamasında *"Bu grubun yöneticileri mesaj gönderme yeteneğinizi kısıtladı"* uyarısı çıkararak metin kutusunu kilitliyor ve kullanıcının `Mersin 545` yazarak doğrulanmasını imkansız kılıyordu.
- **Çözüm:** Telegram API kısıtlaması **asla uygulanmaz**. Kullanıcının mesaj kutusu açık kalır. Doğrulanmamış kullanıcının gönderdiği mesaj Baro/Sicil formatında değilse bot mesajı anında siler (`message.delete()`) ve geçici uyarı gösterir. Kullanıcı doğrudan grupta baro ve sicilini yazarak doğrulanabilir.

### 2. Yönetim Grubu Mesaj Kirliliğinin Önlenmesi (Thread/ID Gruplama) (`audit_service.py`)
- **Eski Durum:** Aday ile ilan sahibi arasındaki her bir köprü mesajı yönetim grubuna ayrı mesaj olarak düşüyordu. Bu durum yüzlerce mesajlık kaosa neden oluyordu.
- **Çözüm:**
  - Köprüdeki tüm mesajlar doğrudan PostgreSQL `MessageLog` tablosuna kaydedilir.
  - Yönetim grubunda her ilan için **tek bir ana bildirim mesajı** oluşturulur (`redis_queue.set_admin_listing_message_id`).
  - Eşleşme, görüşme başlangıcı, anlaşma, tarife ihlali ve zaman aşımı gibi kritik olaylar bu kök mesaja **`reply_to_message_id`** ile thread olarak bağlanır.
  - Adminler için mesaja `[📜 Mesaj Logları]` inline butonu eklenmiştir; basıldığında tüm konuşma dökümü tek pencerede listelenir.

### 3. Ceza Puanlarının Grupta Duyurulması (`confirmation.py` & `admin_panel.py`)
- Şartname gereği, bir ilan nedeniyle adaya veya ilan sahibine ceza puanı uygulandığında (Tarife altı teklif Direkt Ban, 30 dk zaman aşımı veya admin disiplin cezası), bot bu durumu ilanın yayınlandığı ana Telegram grubunda şeffaf bir duyuru mesajıyla paylaşır.

### 4. İlan Sahibinin Görevlendirme Odasına Yönlendirilmesi (`application.py`)
- İlan sahibi kendi ilanındaki `[📋 Başvur]` butonuna basamaz (engellenir).
- Başvuru varsa ilan sahibine `[🎯 Görevlendirmeye Git]` butonu sunulur ve DM üzerinden görüşme/onay paneline yönlendirilir.

### 5. Sıfırlama ve Test Mekanizmaları (`admin_panel.py`)
- Geliştirme ve test aşamasında adminler DM veya gruptan `/sifirla` ve `/baro_sifirla` komutlarını çalıştırabilir.
- Bu komutlar sadece veritabanını temizlemekle kalmaz; Telegram üzerinde geçmişte kısıtlanmış üyelerin (`can_send_messages`) izinlerini otomatik olarak açar (`unrestrict_all_group_members`).

---

## 🧪 5. Test ve Doğrulama

Projeyi test etmek için yerel sanal ortamda:

```bash
# Testleri çalıştırma
PYTHONPATH=. ./.venv/bin/pytest tests/ -v
```

Mevcut durumda **35 testin tamamı eksiksiz geçmektedir.**

---

## 🚀 6. Yeni Ajan İçin Kontrol Listesi (Checklist)

Projeyi devraldığınızda:
1. `git status` ve `git log -n 5` ile son commitleri inceleyin.
2. `tests/` dizinindeki testleri çalıştırarak ortamın sağlıklı olduğunu doğrulayın (`pytest`).
3. Herhangi bir kod değişikliğinde testleri güncelleyin ve yeni test ekleyin.
4. Sunucuya deployment yaparken `git push origin main` sonrası canlı sunucuda `git pull && docker compose restart bot` çalıştırmayı unutmayın.
5. Kullanıcı izinleri ile ilgili işlemlerde Telegram API `restrict_chat_member` ile kullanıcının yazı yazma alanını tamamen kilitlemekten kaçının.

---
**Telif ve Mülkiyet:** Av. Serkan SAYOĞLU
