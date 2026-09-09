# Admin Denetim ve Yönetim Rehberi

Bu rehber, Telegram Avukat Tevkil Botu'nun yöneticileri için denetim grubu işleyişini, acil müdahale protokollerini ve admin komutlarını açıklamaktadır.

---

## 1. Admin Denetim Grubu Mantığı

Sistemde açılan tüm tevkil ilanları, yapılan başvurular ve taraflar arasındaki tüm DM yazışmaları anlık olarak yöneticilerin bulunduğu **"Admin Denetim Grubu"**na aktarılır.

### Log Formatı
Grupta her mesaj şu başlıkla paylaşılır:
```text
🛡️ [DENETİM LOGU — İlan #104]
👤 Gönderen: İlan Sahibi - Av. Ahmet Yılmaz (@ahmetyilmaz) (ID: 123456789)
🎯 Hedef: 1. Sıra Aday
⏰ Zaman: 06.09.2026 14:35:10
────────────────────
💬 Mesaj:
Dosya no: 2026/123 Esas, saat 10:00'daki duruşmaya yetki belgesiyle girilecek.
```

Fotoğraf, ses kaydı ve PDF dosyaları da orijinal halleriyle aynı başlıkla bu gruba kopyalanır.

---

## 2. Admin Yönetim Komutları

Admin komutları doğrudan **Admin Denetim Grubu** içerisinden çalıştırılır.

### A. Görüşmeyi Durdurma (`/durdur`)
* **Kullanım:** `/durdur <ilan_id>`
* **Sonuç:** Köprü anında kesilir, taraflara bildirilir ve ilan durumu `CANCELLED_ADMIN` olarak kaydedilir.

### B. Kullanıcı Kısıtlama / Ban (`/kullanici_kisitla`)
* **Kullanım:** `/kullanici_kisitla <user_id> [gün_sayısı] [gerekçe]`
* *Örnek:* `/kullanici_kisitla 123456789 5 Anlaşmazlık sonrası uygunsuz üslup`
* **Sonuç:** Kullanıcı belirtilen gün boyunca ilan açamaz ve başvuramaz.

### C. Kısıtlamayı Kaldırma (`/ceza_kaldir`)
* **Kullanım:** `/ceza_kaldir <user_id>`

### D. Ceza Puanı Verme (`/ceza_puani_ver`)
* **Kullanım:** `/ceza_puani_ver <user_id> <puan> [sebep]`
* *Örnek:* `/ceza_puani_ver 123456789 15 Göreve mazeretsiz katılmama`
* **Sonuç:** Kullanıcının ceza puanı artar ve başvuru sırasına kademeli handikap (1-4 sıra geriden başlama) eklenir.

### E. Rank Puanı Ekleme (`/puan_ekle`)
* **Kullanım:** `/puan_ekle <user_id> <puan>`

### F. Kullanıcı Bilgi Kartı (`/kullanici_bilgi`)
* **Kullanım:** `/kullanici_bilgi <user_id>`
* **Sonuç:** Kullanıcının rank puanı, ceza puanı, handikap seviyesi, baro sicili ve geçmiş işlem istatistikleri dökülür.

### G. İlan Detayı İnceleme (`/ilan_detay`)
* **Kullanım:** `/ilan_detay <ilan_id>`
* **Sonuç:** İlan sahibi, sıradaki tüm başvuranlar ve loglanan mesaj sayıları görüntülenir.

### H. Aktif Görüşmeleri Listeleme (`/aktif_ilanlar`)
* **Kullanım:** `/aktif_ilanlar`

### I. Yasaklı Kullanıcıları Listeleme (`/kara_liste`)
* **Kullanım:** `/kara_liste`

### J. Sistem İstatistikleri (`/istatistik`)
* **Kullanım:** `/istatistik`

---

## 3. Otomatik İşleyen Sistem Kuralları

1. **30 Dakika Kuralı:** İlan sahibi 1. adayla eşleştikten sonra 30 dakika içinde ilk mesajı atmazsa bot ilanı iptal eder, ilan sahibini otomatik **5 gün** kısıtlar, **+20 Ceza Puanı** işler ve gruba iptal duyurusu geçer.
2. **Anlaşamama & Zincirleme Sıra Devri:** İlan sahibi `[Anlaşamadık]` seçip sebep olarak **Ücret harici** (Mesafe, Kıdem vb.) bir gerekçe bildirdiğinde sistem otomatik olarak sıradaki adaya devir teklifi götürür; ret durumunda yedek sıradaki sonraki adaylara zincirleme aktarılır.
3. **Başarılı Tevkil Ödülü:** `[🤝 Anlaştık]` teyidinde her iki tarafın hesabına **+5 Rank Puanı** eklenir.
