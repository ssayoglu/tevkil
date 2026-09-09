# Telegram Avukat Tevkil Botu

Avukatlar arasındaki tevkil ilanlarını otomatize eden, başvuruları milisaniye hassasiyetli bir sıra sistemine sokan, tarafları güvenli ve anonim şekilde köprüleyen (bridge), zaman aşımı ve ceza mekanizmalarını yöneten ve tüm süreci bir Admin Denetim Grubu üzerinden gözetim altında tutan uçtan uca Telegram Bot sistemi.

---

## 🌟 Öne Çıkan Özellikler

1. **Akıllı İlan Tespiti & Şeffaf Canlı Başvuru Panosu:**
   - Gruplarda *"tevkildir"* kelimesi geçen mesajları anında yakalar ve `[📋 Başvur]` butonu içeren bir yanıt mesajı paylaşır.
   - Butona tıklandıkça gruptaki mesaj anlık güncellenir; kimin hangi saat, dakika ve milisaniyede başvurduğu şeffaf bir şekilde herkes tarafından görülür.
2. **Milisaniye Hassasiyetli Adil Kuyruk (Redis Sorted Set):**
   - Yarış durumlarını (race condition) engelleyen atomik milisaniye skoru ile ilk tıklayan meslektaşımız anında görüşme başlatma hakkı kazanır.
   - Yedek sıradaki adaylara sıraları bildirilir.
3. **Anonim Köprüleme (Bridge):**
   - Tarafların Telegram profilleri/numaraları gizli tutulur.
   - Metin, fotoğraf ve PDF/belge gönderimleri bot aracılığıyla çift yönlü iletilir.
4. **30 Dakika Kuralı & Otomatik Cezai Müeyyideler:**
   - Eşleşme sonrası ilan sahibi 30 dakika içinde ilk mesajı atmazsa ilan otomatik iptal edilir.
   - İlan sahibi sistem tarafından **5 gün süreyle kara listeye alınır** (yeni ilan veremez, başvuramaz).
   - Ana gruba iptal duyurusu geçilir.
5. **Anlaşma Teyit & Akıllı Sıra Devri:**
   - İlan sahibinin ekranında `[🤝 Anlaştık]` ve `[❌ Anlaşamadık]` butonları yer alır.
   - Anlaşamama durumunda sebep seçilir (Ücret, Mesafe, Kıdem vb.).
   - Gerekçe "Ücret" haricindeyse sistem otomatik olarak sıradaki 2. adaya devir teklifi gönderir.
6. **Merkezi Admin Denetimi & Müdahale:**
   - Taraflar arasındaki tüm mesaj, fotoğraf ve PDF'ler yöneticilerin bulunduğu özel **"Denetim Grubu"**na anlık klonlanır.
   - Adminler panelden görüşmeyi anında durdurabilir (`/durdur`) veya kullanıcıları kısıtlayabilir (`/kullanici_kisitla`).

---

## 🚀 Hızlı Başlangıç

### Gereksinimler
- Docker & Docker Compose
- Telegram Bot Token ([@BotFather](https://t.me/BotFather))
- Admin Denetim Grubu Chat ID

### 1. Ortam Değişkenlerini Ayarlayın
```bash
cp .env.example .env
```
`.env` dosyasındaki `BOT_TOKEN` ve `ADMIN_CHAT_ID` alanlarını doldurun.

### 2. Tek Komutla Çalıştırın
```bash
docker compose up -d --build
```

Bot, PostgreSQL ve Redis servisleri ayağa kalkacak ve bot hazır olacaktır.

---

## 📚 Dokümantasyon

- [Admin Denetim ve Yönetim Rehberi](docs/admin_guide.md)
- [Ubuntu Linux VPS Kurulum Kılavuzu](docs/deployment_guide.md)

---

## ⚖️ Lisans ve Telif
Proje Şartnamesi: **Av. Serkan SAYOĞLU** (17.02.2026)
