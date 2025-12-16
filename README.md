# 🤖 MHRS Takip Botu (Telegram)

MHRS Takip Botu, Türkiye’deki 🏥 **MHRS (Merkezi Hekim Randevu Sistemi)** üzerinden  
randevuları otomatik olarak takip eden bir **Telegram botudur**.  
Belirlediğiniz 📍 **il, ilçe, klinik** ve 📅 **tarih aralığı** için boş randevu bulunursa  
sizi 📲 **Telegram’dan bildirir** veya isterseniz 🤖 **otomatik randevu alır**.

> ⚠️ Bu proje resmi MHRS servisi değildir.  
> 🎓 Eğitim ve otomasyon amaçlıdır.

---

## ✨ Özellikler

- 🔐 **Token ile giriş**
- 🪪 **TC / Şifre ile giriş** (token düşerse 🔁 **401’de otomatik yenileme**)
- 📢 Boş randevu bulunca Telegram bildirimi
- 🤖 İsteğe bağlı **otomatik randevu alma**
- 📅 Tarih aralığı seçebilme
- 🧠 Anti-spam mantığı  
  - ⏱️ 55–95 saniye rastgele bekleme  
  - 😴 10 denemeden sonra %80 ihtimalle 5–10 dk uzun mola
- 🧾 MHRS uyarı mesajlarını (RND4034 vb.) **HTML temizleyerek loglama**

---

## 🔧 Kurulum

### 1️⃣ Python
🐍 **Python 3.10+** önerilir.

### 2️⃣ Gerekli kütüphaneler
```bash
pip install -r requirements.txt
```

**requirements.txt** içinde en az:
- `python-telegram-bot>=20`
- `requests`

### 3️⃣ Telegram Bot Token ayarlama
📂 `telegram.py` dosyasının en altındaki satıra token’ı yaz:

```python
BOT_TOKEN = "TELEGRAM_BOT_TOKEN_BURAYA"
```

### 4️⃣ Botu çalıştır 🚀

**Windows**
```bash
py -3.10 telegram.py
```

**Linux / macOS**
```bash
python3 telegram.py
```

Terminalde **📡 Bot çalışıyor...** yazısını görmelisin.

---

## 🤖 Telegram Bot Token Nasıl Alınır?

1. Telegram’da 👉 **@BotFather**
2. `/start`
3. `/newbot`
4. Bot ismi ve kullanıcı adı belirle
5. BotFather sana şu formatta bir token verir:

```
1234567890:AAH-R7vyraom5aDQrgkZEJJZ08Bc1XUJ-CY
```

Bu token’i `telegram.py` içindeki `BOT_TOKEN` değişkenine yapıştır.

---

## 🏥 MHRS Giriş Yöntemleri

Bot **iki giriş yöntemini** destekler:

### 🔐 1) Token ile giriş (kolay)

**Web:**
- https://www.mhrs.gov.tr giriş yap
- **F12 → Network**
- Bir isteği seç
- **Headers** kısmında  
  `Authorization: Bearer xxxxx`
- **Bearer** yazısını silip token’ı bot’a gönder

**Mobil (HttpCanary):**
- HttpCanary kur
- MHRS mobil uygulamasında giriş yap
- `/kurum-rss` içeren isteği bul
- Authorization değerini kopyala
- Bot’a gönder

> ℹ️ Token düşerse bot senden tekrar `/start` ister.

---

### 🪪 2) TC / Şifre ile giriş (⭐ önerilen)

- Bot MHRS’ye senin adına giriş yapar
- Token düşerse **401 hatasında otomatik yeniler**
- 5 deneme başarısız olursa ⏳ **60 dakika mola verir**

---

## 🚀 Kullanım

1️⃣ Botu başlat:
```
/start
```

2️⃣ Giriş yöntemini seç:
- `1` → Token
- `2` → TC / Şifre

3️⃣ Sırasıyla seçim yap:
- 📍 İl plakası
- 🏘️ İlçe
- 🏥 Klinik
- ⚙️ Mod  
  - `1` Otomatik al 🤖  
  - `2` Sadece bildir 📢
- 📅 Tarih aralığı (gg.aa.yyyy)

4️⃣ Boş randevu bulununca:
- 📢 Bildirim modu → mesaj gelir
- 🤖 Otomatik mod → randevu alınır + mesaj gelir

---

## ⏱️ Tarama Mantığı

Bot MHRS’yi spamlamamak için insan benzeri çalışır 🧠

- ⏳ Her denemede **55–95 saniye** rastgele bekler
- 😴 En az **10 denemeden sonra**, %80 ihtimalle **5–10 dk uzun mola** verir

---

## 📅 Tarih Aralığı (Kayan Pencere)

Kullanıcı bir tarih aralığı seçer  
(örn: **01.01.2026 – 10.01.2026**)

Bot:
- Gün farkını hesaplar 📊
- Her sorguda aralığı **bugünden itibaren kaydırarak** tarar ⏩

---

## 🛠️ Komutlar

- `/start` → Yeni takip başlat 🚀
- `/dur` → Tüm takipleri durdur ⏹️
- `/iptal` → Seçim akışını iptal et ❌
- `/yardim` → Yardım / rehber 📘

---

## ⚠️ Olası Hatalar ve Çözümleri

### ❌ Hata
```
TypeError: AsyncClient.__init__() got an unexpected keyword argument 'proxies'
```

**Sebep:**  
`python-telegram-bot` ve `httpx` sürüm uyumsuzluğu

**Çözüm:**
```bash
pip install --force-reinstall httpx==0.27.0
```

---

## 👨‍💻 Geliştirici

**Akın**  
💻 GitHub: https://github.com/4kinn  

---

## 📌 Sorumluluk Reddi

Bu bot tamamen 🎓 **eğitim ve otomasyon amaçlıdır**.  
MHRS’nin resmi servisi değildir.  
Kullanım sorumluluğu kullanıcıya aittir.
