# 🤖 AGENT HANDOFF & PROJE GELİŞTİRME REHBERİ

> **Bu Belge Hakkında:** Bu dosya, projeyi başka bir bilgisayarda veya ortamda devralacak **AI Ajanı (Antigravity / Cursor / Claude / GPT vb.)** ve geliştirici meslektaşlarımız için hazırlanmıştır. Projenin tüm arka planını, şartname kurallarını, mimari kararları, mevcut kod durumunu ve yapılacak sonraki adımları içerir.

---

## 📌 1. Proje Özeti ve Amacı

Bu proje, **Av. Serkan SAYOĞLU** tarafından hazırlanan **17.02.2026** tarihli Teknik Şartname doğrultusunda geliştirilen bir **Telegram Avukat Tevkil Yönetim Botu**dur.

### Temel Hedef:
Telegram hukuk gruplarında paylaşılan tevkil ilanlarını otomatik olarak tespit etmek (doğrudan `"tevkildir"` veya Türkiye'nin tüm il/ilçe adliyeleri ve duruşma/evrak/katılacak görev bağlamı içeren mesajlar), başvuruları milisaniye hassasiyetli adil bir sıra sistemine sokmak, tarafları bot üzerinden gizlilik esasıyla (anonim) çift yönlü köprülemek (bridge), zaman aşımı ve ceza kurallarını işletmek, **Rank & Ceza Puanı, Kademeli Handikap ve Tarife Altı Ücret Direkt Ban** mekanizması ile güvenilirliği sağlamak ve tüm süreci yöneticilerin bulunduğu özel bir **Admin Denetim Grubu** üzerinden gözetim altında tutmaktır.

---

## 📜 2. Teknik Şartname ve İş Mantığı Kuralları

### A. İlan Takibi ve Akıllı Adliye Tespiti (`group_detector.py` & `courthouses.py`)
1. **Akıllı Adliye & Kelime Filtresi:**
   - Hukuk grubunda paylaşılan mesajlarda `"tevkildir"` kelimesi aranır.
   - **Tüm İl ve İlçe Adliyeleri Tespiti:** Türkiye'de adliyesi/mülhakatı bulunan 81 il ve tüm ilçeler (örn. Bursa, Bayramiç, Çağlayan, Kartal, Bakırköy, Çorlu, Bodrum, Kuşadası, İnegöl vb.) mesajda geçiyorsa ve duruşma/evrak teslimi/katılacak var mı/meslektaş aranıyor bağlamı varsa bot bunu otomatik tevkil ilanı olarak tespit eder.
   - **Negatif İstisna:** Eğer mesaj içerisinde `"tevkil değildir"`, `"tevkil değil"` gibi ifadeler geçiyorsa kesinlikle tevkil sayılmaz (`False`).
2. **İlan Sahibine Harici DM Atılmasını Engelleme (Anti-Bypass Koruması):**
   - Bot grupta admin ise kullanıcının orijinal mesajını anında siler (`message.delete()`), böylece diğer üyelerin mesaj sahibinin profiline/avatarına tıklayıp harici DM atması engellenir.
   - İlan metni ve canlı başvuru panosu bot tarafından anonim olarak (`👤 İlan Sahibi: Meslektaşımız (⭐ 105 Puan)`) yayınlanır.
3. **Canlı Şeffaf Başvuru Panosu (`application.py`):**
   - Kullanıcılar butona tıkladıkça bot, gruptaki yanıt mesajını Türkiye saatine (`Europe/Istanbul`) göre `HH:MM:SS.mmm` hassasiyetiyle anlık günceller.
   - Her adayın **Rank Puanı**, **Handikap Durumu** ve **Anlık Süreç Durumu** (`[🟢 Görüşmede]`, `[⏳ Yedek Sırada]`, `[🤝 Anlaşıldı]`, `[❌ Anlaşılamadı]`, `[🚫 Reddetti]`) gösterilir.
4. **Milisaniye Sıralama ve Kademeli Handikap Algoritması (`redis_queue.py` & `rank_service.py`):**
   - Redis Sorted Set (`ZADD ... timestamp_ms`) ile atomik olarak kaydedilir (race condition engellenir).
   - **Sadece ilk tıklayan kişi (1. sıra)** görüşme başlatma hakkı kazanır.
   - Diğer adaylara sırası özel mesajla iletilir.

### B. ⭐ Rank, Ceza Puanı ve Kademeli Sıra Handikapı (`rank_service.py`)
1. **Rank Puanı (Varsayılan: 100):** Başarıyla sonuçlanan her tevkil için hem ilan sahibine hem de adaya **+5 Puan** verilir.
2. **Ceza Puanı:**
   - 30 dakika kuralı ihlali (ilk mesajı göndermeme): **+20 Ceza Puanı** ve 5 gün sistem banı.
   - Tarife altı teklif ihlali: **+30 Ceza Puanı** ve 15 gün Direkt Ban.
   - Admin cezaları: **+10 ila +30 Ceza Puanı** (`/ceza_puani_ver`).
3. **Efektif Net Puan:** `max(0, rank_score - penalty_points)`.
4. **Kademeli Sıra Handikapı (1-2-3-4 Sıra Geriden Başlama):**
   - Kullanıcının puanı sistem ortalamasının altındaysa veya ceza puanı varsa `[📋 Başvur]` butonuna bastığında milisaniyesine sanal gecikme eklenir:
     - *Seviye 1:* +3.000 ms (1 sıra geriye atma eğilimi)
     - *Seviye 2:* +7.000 ms (2 sıra geriye atma eğilimi)
     - *Seviye 3:* +15.000 ms (3 sıra geriye atma eğilimi)
     - *Seviye 4:* +30.000 ms (4+ sıra geriye atma eğilimi)

### C. 🚨 Tarife Altı Ücret Teklifinde Doğrudan Ban (Direkt Ban)
- Baro Asgari Ücret Tarifesi veya grup asgari tarifesi altında ücret teklif edilmesi meslek etiği gereği yasaktır.
- `[❌ Anlaşamadık]` seçilip `[🚨 Tarife Altı Teklif (Direkt Ban)]` işaretlendiğinde ihlali yapan kullanıcı **15 gün süreyle doğrudan sistemden men edilir (Direkt Ban)** ve hesabına **+30 Ceza Puanı** işlenir.
- Admin Denetim Grubu'na yüksek öncelikli kırmızı alarm iletilir.

### D. Anonim Köprüleme (Bridge) ve İletişim (`bridge_service.py` & `bridge_chat.py`)
1. **Gizlilik:** Tarafların Telegram profilleri/numaraları karşı tarafa gizlenir. Bot mesajları `[İlan Sahibi]` ve `[X. Sıra Başvuran Aday]` etiketleriyle iletir.
2. **Medya Desteği:** Sistem metin mesajlarının yanı sıra **fotoğraf**, **ses kaydı (voice)** ve **PDF/doküman** gönderimini destekler.

### E. Zaman Aşımı (30 Dk Kuralı) ve Cezai Müeyyideler (`timeout_service.py`)
1. **30 Dakika Kuralı:** İlan sahibi eşleşme sağlandıktan sonra 30 dakika içinde ilk mesajı göndermezse ilan iptal edilir.
2. **Otomatik Kara Liste ve Ceza:** İlan sahibi **5 gün süreyle kara listeye alınır** ve hesabına **+20 Ceza Puanı** işlenir.
3. **Dirençli Arka Plan Denetleyicisi:** Veritabanındaki `timeout_at` alanı ve her 60 saniyede bir çalışan `run_periodic_timeout_checker` sayesinde sunucu/bot yeniden başlasa dahi zaman aşımı aksamaz.
4. **Grup Duyurusu:** İptal olan ilan ana grupta bot tarafından duyurulur ve pano güncellenir.

### F. Anlaşma Teyit ve Zincirleme Sıra Devri (`confirmation.py`)
1. İlan sahibi `[🤝 Anlaştık]` seçerse ilan `COMPLETED` olur, taraflara teşekkür mesajı gider, her iki tarafa **+5 Rank Puanı** verilir ve pano güncellenir.
2. `[❌ Anlaşamadık]` seçilirse sebep istenir (`[🚨 Tarife Altı Teklif]`, `[💰 Ücret]`, `[📍 Mesafe]`, `[🎓 Kıdem]`, `[❓ Diğer]`).
3. **Zincirleme Devir:** Sebep **"Ücret" haricinde** seçilirse sistem otomatik olarak sıradaki adaya teklif iletir. Teklif reddedilirse (`decline`) zincir bir sonraki yedek adaya (varsa) devredilir.

### G. Kullanıcı ve Admin Komutları
1. **Kullanıcı DM Komutları (`user_panel.py`):**
   - `/start` - Başlangıç, rank puanı, handikap durumu ve yönlendirmeler.
   - `/yardim` - Sistem kuralları, tarife yasağı ve detaylı kullanım rehberi.
   - `/profilim` / `/durum` - Detaylı rank puanı, ceza dökümü ve ban durumu.
   - `/ilanlarim` - Kullanıcının açtığı son ilanlar.
   - `/basvurularim` - Kullanıcının yaptığı son başvurular.
   - `/baro_kaydet <Baro> <Sicil>` - Baro levha ve sicil doğrulama.
2. **Admin Denetim Grubu Komutları (`admin_panel.py`):**
   - `/admin_yardim` - Admin komut listesi.
   - `/durdur <ilan_id>` - Aktif görüşmeyi anında sonlandırır.
   - `/tarife_ban <user_id> [gün] [sebep]` - Tarife ihlaline doğrudan ban uygular.
   - `/kullanici_kisitla <user_id> [gün] [sebep]` - Kullanıcıyı süreli kısıtlar.
   - `/ceza_kaldir <user_id>` - Kısıtlamayı kaldırır.
   - `/ceza_puani_ver <user_id> <puan> [sebep]` - Ceza puanı ekler.
   - `/puan_ekle <user_id> <puan>` - Rank puanı ekler.
   - `/kullanici_bilgi <user_id>` - Kullanıcı bilgi kartını görüntüler.
   - `/ilan_detay <ilan_id>` - İlanın başvuru kuyruğunu ve denetim log sayısını görüntüler.
   - `/aktif_ilanlar` - Devam eden tüm köprü görüşmelerini listeler.
   - `/kara_liste` - Halihazırda yasaklı kullanıcıları listeler.
   - `/istatistik` - Sistem geneli tevkil, kullanıcı ve işlem istatistikleri.

---

## 🏗️ 3. Mimari ve Dizin Yapısı

```
.
├── Dockerfile                  # Bot container tanımı (Python 3.12-slim)
├── docker-compose.yml          # PostgreSQL 16, Redis 7 ve Bot orkestrasyonu
├── deploy.sh                   # Tek komutla VPS sunucu kurulum scripti
├── requirements.txt            # aiogram 3.x, sqlalchemy, asyncpg, redis, pydantic-settings
├── .env.example                # Örnek ortam değişkenleri
├── README.md                   # Genel proje dokümantasyonu
├── AGENT_HANDOFF.md            # Bu rehber (Ajan / Geliştirici devir kılavuzu)
├── docs/
│   ├── admin_guide.md          # Admin yönetim komutları ve panel dokümanı
│   └── deployment_guide.md     # Ubuntu VPS sunucu kurulum rehberi
├── bot/
│   ├── main.py                 # Bot başlatıcı, periyodik checker ve router kayıtları
│   ├── config.py               # Pydantic Settings ortam değişkenleri
│   ├── database/
│   │   ├── connection.py       # Async SQLAlchemy session yöneticisi
│   │   └── models.py           # User, Listing, Application, BridgeSession, MessageLog, PenaltyLog
│   ├── services/
│   │   ├── redis_queue.py      # ZADD milisaniye sıralama ve lock mekanizması
│   │   ├── rank_service.py     # Rank, ceza puanı ve kademeli handikap servisi
│   │   ├── baro_service.py     # Baro Sicil / Levha doğrulama altyapısı
│   │   ├── bridge_service.py   # Anonim DM mesaj/fotoğraf/ses/PDF iletim motoru
│   │   ├── timeout_service.py  # 30 dk zamanlayıcı ve dirençli arka plan denetleyicisi
│   │   └── audit_service.py    # Admin denetim grubuna anlık klonlama servisi
│   ├── handlers/
│   │   ├── user_panel.py       # /start, /yardim, /profilim, /ilanlarim, /basvurularim
│   │   ├── group_detector.py   # Adliye NLP filtresi, anti-bypass ve ilan yakalama
│   │   ├── application.py      # 'Başvur' buton callback ve canlı pano güncellemesi
│   │   ├── bridge_chat.py      # İlan sahibi ve aday arasındaki anonim DM mesajlaşması
│   │   ├── confirmation.py     # [Anlaştık] / [Anlaşamadık] / Tarife Ban / Sıra Devri
│   │   └── admin_panel.py      # Admin müdahale ve istatistik komutları
│   ├── middlewares/
│   │   ├── db_session.py       # Async SQLAlchemy session middleware
│   │   └── blacklist_check.py  # Kara liste ve ceza kontrol middleware
│   └── utils/
│       ├── courthouses.py      # Türkiye 81 il + tüm ilçe adliyeleri veri seti & normalizer
│       └── time_utils.py       # Türkiye saat dilimi (Europe/Istanbul) ve ms formatlayıcı
└── tests/
    ├── test_detector.py        # Adliye il/ilçe regex ve negatif istisna testleri
    ├── test_queue_logic.py     # Milisaniye formatlama ve anlaşmazlık yönlendirme testleri
    ├── test_rank_service.py    # Net puan, handikap seviyeleri ve sanal gecikme testleri
    ├── test_baro_service.py    # Sicil format doğrulama testleri
    ├── test_time_utils.py      # Saat dilimi ve ms formatlama testleri
    ├── test_handlers_user_panel.py # Kullanıcı paneli handler testleri
    ├── test_handlers_admin.py  # Admin panel komut testleri
    └── test_confirmation_chain.py # Zincirleme devir ve klavye testleri
```

---

## 💻 4. Kurulum ve Test

```bash
# Sanal ortam oluşturup paketleri kurun:
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest pytest-asyncio pytest-mock

# Tüm otomatik testleri çalıştırın:
PYTHONPATH=. pytest tests/ -v
```

---

## ⚖️ Lisans ve Telif
Proje Şartnamesi: **Av. Serkan SAYOĞLU** (17.02.2026)
