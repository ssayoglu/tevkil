# Telegram Avukat Tevkil Botu

Avukatlar arasındaki tevkil ilanlarını otomatize eden, başvuruları milisaniye hassasiyetli bir sıra sistemine sokan, **Rank & Ceza Puanı ve Kademeli Sıra Handikapı** ile güvenilirliği sağlayan, tarafları güvenli ve anonim şekilde köprüleyen (bridge), zaman aşımı ve ceza mekanizmalarını yöneten ve tüm süreci bir Admin Denetim Grubu üzerinden gözetim altında tutan uçtan uca Telegram Bot sistemi.

---

## 🌟 Öne Çıkan Özellikler

1. **Akıllı İlan Tespiti & Şeffaf Canlı Başvuru Panosu:**
   - Gruplarda *"tevkildir"* kelimesi geçen mesajları anında yakalar ve `[📋 Başvur (Sıraya Gir)]` butonu içeren bir yanıt mesajı paylaşır.
   - Butona tıklandıkça gruptaki mesaj anlık güncellenir; kimin hangi saat, dakika ve milisaniyede başvurduğu, rank puanı ve handikap durumu şeffaf olarak herkes tarafından görülür.
2. **⭐ Rank, Ceza Puanı ve Kademeli Sıra Handikapı:**
   - Başarıyla tamamlanan her tevkil için taraflara **+5 Puan** verilir.
   - 30 dakika kuralı ihlalinde **+20 Ceza Puanı** ve 5 gün ban uygulanır.
   - Puanı sistem ortalamasının altında olan veya ceza puanı bulunan kullanıcılar butona bastığında net puanına göre **1, 2, 3 veya 4 kademe sanal gecikme (handikap)** uygulanarak geriden sıraya yerleştirilir.
3. **Milisaniye Hassasiyetli Adil Kuyruk (Redis Sorted Set):**
   - Yarış durumlarını (race condition) engelleyen atomik milisaniye skoru ile ilk sıradaki meslektaşımız doğrudan görüşme başlatma hakkı kazanır.
   - Yedek sıradaki adaylara sıraları bildirilir.
4. **Anonim Köprüleme (Bridge):**
   - Tarafların Telegram profilleri/numaraları gizli tutulur.
   - Metin, fotoğraf, ses kaydı ve PDF/belge gönderimleri bot aracılığıyla çift yönlü iletilir.
5. **Dirençli 30 Dakika Kuralı & Otomatik Cezai Müeyyideler:**
   - Eşleşme sonrası ilan sahibi 30 dakika içinde ilk mesajı atmazsa ilan otomatik iptal edilir.
   - Bot ve sunucu yeniden başlasa bile veritabanı destekli arka plan denetleyicisi sayesinde zaman aşımı aksamaz.
   - İlan sahibi **5 gün süreyle kara listeye alınır** ve **+20 Ceza Puanı** işlenir.
6. **Anlaşma Teyit & Zincirleme Sıra Devri:**
   - İlan sahibinin ekranında `[🤝 Anlaştık]` ve `[❌ Anlaşamadık]` butonları yer alır.
   - Anlaşamama durumunda sebep seçilir (Ücret, Mesafe, Kıdem vb.).
   - Gerekçe "Ücret" haricindeyse sistem otomatik olarak sıradaki adaya devir teklifi gönderir; ret halinde zincirleme olarak sonraki adaya geçer.
7. **Merkezi Admin Denetimi & Müdahale:**
   - Taraflar arasındaki tüm mesaj, fotoğraf, ses ve PDF'ler yöneticilerin bulunduğu özel **"Denetim Grubu"**na anlık klonlanır.
   - Adminler panelden görüşmeyi durdurabilir (`/durdur`), kullanıcıyı kısıtlayabilir (`/kullanici_kisitla`), ceza puanı verebilir (`/ceza_puani_ver`), kullanıcı ve ilan kartlarını inceleyebilir (`/kullanici_bilgi`, `/ilan_detay`) ve sistem istatistiklerini görebilir (`/istatistik`).
8. **Kullanıcı Self-Servis DM Paneli:**
   - Kullanıcılar özel mesajda `/start`, `/yardim`, `/profilim`, `/ilanlarim`, `/basvurularim` ve `/baro_kaydet` komutlarını kullanabilir.

---

## 🚀 Hızlı Başlangıç

### Gereksinimler
- Docker & Docker Compose (veya Python 3.9+)
- Telegram Bot Token ([@BotFather](https://t.me/BotFather))
- Admin Denetim Grubu Chat ID

### 1. Ortam Değişkenlerini Ayarlayın
```bash
cp .env.example .env
```
`.env` dosyasındaki `BOT_TOKEN` ve `ADMIN_CHAT_ID` alanlarını doldurun.

### 2. Tek Komutla Çalıştırın (Docker)
```bash
docker compose up -d --build
```

### 3. Yerel Testleri Çalıştırma
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest pytest-asyncio pytest-mock

PYTHONPATH=. pytest tests/ -v
```

---

## 📚 Dokümantasyon

- [Admin Denetim ve Yönetim Rehberi](docs/admin_guide.md)
- [Ubuntu Linux VPS Kurulum Kılavuzu](docs/deployment_guide.md)
- [Agent Handoff & Geliştirme Rehberi](AGENT_HANDOFF.md)

---

## ⚖️ Lisans ve Telif
Proje Şartnamesi: **Av. Serkan SAYOĞLU** (17.02.2026)
