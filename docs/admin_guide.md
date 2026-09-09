# Admin Denetim ve Yönetim Rehberi

Bu rehber, Telegram Avukat Tevkil Botu'nun yöneticileri için denetim grubu işleyişini, acil müdahale protokollerini ve admin komutlarını açıklamaktadır.

---

## 1. Admin Denetim Grubu Mantığı

Sistemde açılan tüm tevkil ilanları, yapılan başvurular ve taraflar arasındaki tüm DM yazışmaları anlık olarak yöneticilerin bulunduğu **"Admin Denetim Grubu"**na aktarılır.

### Log Formatı
Grupta her mesaj şu başlıkla paylaşılır:
```
🛡️ [DENETİM LOGU — İlan #104]
👤 Gönderen: İlan Sahibi - Av. Ahmet Yılmaz (@ahmetyilmaz) (ID: 123456789)
🎯 Hedef: 1. Sıra Aday
⏰ Zaman: 06.09.2026 14:35:10
────────────────────
💬 Mesaj:
Dosya no: 2026/123 Esas, saat 10:00'daki duruşmaya yetki belgesiyle girilecek.
```

Fotoğraf ve PDF dosyaları da orijinal halleriyle aynı başlıkla bu gruba kopyalanır.

---

## 2. Admin Yönetim Komutları

Admin komutları doğrudan **Admin Denetim Grubu** içerisinden çalıştırılır.

### A. Görüşmeyi Durdurma (`/durdur`)
* **Amaç:** Taraflar arasında tartışma, kurallara aykırı talep veya şüpheli bir durum tespit edildiğinde devam eden görüşmeyi tek komutla sonlandırmak.
* **Kullanım:**
  ```text
  /durdur <ilan_id>
  ```
  *Örnek:* `/durdur 104`
* **Sonuç:**
  - Köprü anında kesilir, tarafların birbirine mesaj göndermesi engellenir.
  - İlan sahibine ve adaya: *"Görüşme yöneticilerimiz tarafından denetim gereği sonlandırılmıştır"* mesajı gider.
  - İlan durumu `CANCELLED_ADMIN` olarak kaydedilir.

---

### B. Kullanıcı Kısıtlama / Ban (`/kullanici_kisitla`)
* **Amaç:** Kural ihlali yapan, meslek etiğine uymayan veya sistemi kötüye kullanan kullanıcıyı geçici veya süreli olarak engellemek.
* **Kullanım:**
  ```text
  /kullanici_kisitla <user_id> [gün_sayısı] [gerekçe]
  ```
  *Örnek:* `/kullanici_kisitla 123456789 5 Anlaşmazlık sonrası uygunsuz üslup`
* **Sonuç:**
  - Kullanıcı belirtilen gün boyunca grupta `tevkildir` ilanı açamaz ve ilanlara başvuramaz.
  - Varsa devam eden aktif görüşmesi anında kesilir.
  - Kullanıcıya kısıtlandığına dair gerekçeli bildirim iletilir.

---

### C. Kısıtlamayı Kaldırma (`/ceza_kaldir`)
* **Amaç:** Süresi dolmadan önce yöneticinin inisiyatifiyle kısıtlamayı kaldırmak.
* **Kullanım:**
  ```text
  /ceza_kaldir <user_id>
  ```
  *Örnek:* `/ceza_kaldir 123456789`

---

### D. Aktif Görüşmeleri Listeleme (`/aktif_ilanlar`)
* **Amaç:** Şu anda devam eden tüm görüşmeleri, ilan ID'lerini ve ilk mesajın atılıp atılmadığını kontrol etmek.
* **Kullanım:**
  ```text
  /aktif_ilanlar
  ```

---

## 3. Otomatik İşleyen Sistem Kuralları

1. **30 Dakika Kuralı:** İlan sahibi 1. adayla eşleştikten sonra 30 dakika içinde ilk mesajı atmazsa bot ilanı iptal eder, ilan sahibini otomatik **5 gün** kısıtlar ve gruba iptal duyurusu geçer.
2. **Anlaşamama & Sıra Devri:** İlan sahibi `[Anlaşamadık]` seçip sebep olarak **Ücret harici** (Mesafe, Kıdem vb.) bir gerekçe bildirdiğinde sistem otomatik olarak 2. adaya devir teklifi götürür.
