🤖 MHRS TAKİP BOTU (TELEGRAM)

MHRS Takip Botu, Türkiye’deki 🏥 **MHRS (Merkezi Hekim Randevu Sistemi)** üzerinden
randevuları otomatik olarak takip eden bir Telegram botudur.
Belirlediğiniz 📍 il, ilçe, klinik ve 📅 tarih aralığı için boş randevu bulunursa
sizi 📲 **Telegram’dan bildirir** veya isterseniz 🤖 **otomatik randevu alır**.

⚠️ Bu proje resmi MHRS servisi değildir.  
🎓 Otomasyon / eğitim amaçlıdır.


✨ ÖZELLİKLER

✅ Token ile giriş desteği  
🪪 TC / Şifre ile giriş desteği (token düşerse 🔁 **401’de otomatik yenileme**)  
📢 Boş randevu bulunca Telegram’dan bildirim  
🤖 İsteğe bağlı otomatik randevu alma  
📅 Tarih aralığı seçebilme  
🧠 Anti-spam mantığı:
   ⏱️ 55–95 saniye rastgele bekleme  
   😴 10 denemeden sonra %80 ihtimalle 5–10 dakika uzun mola  
🧾 MHRS uyarı mesajlarını (RND4034 vb.) HTML temizleyerek loglama  


🔧 KURULUM

1️⃣ Python  
🐍 Python **3.10 veya üzeri** önerilir.

2️⃣ Gerekli kütüphaneler  
Terminalde şu komutu çalıştır:

pip install -r requirements.txt

📦 requirements.txt içinde en az şunlar olmalı:
- python-telegram-bot>=20  
- requests  

3️⃣ Telegram Bot Token ayarlama  
📂 `telegram.py` dosyasının en altındaki satıra Telegram bot token’ini yaz:

BOT_TOKEN = "TELEGRAM_BOT_TOKEN_BURAYA"

4️⃣ Botu çalıştırma 🚀

🪟 Windows:
py -3.10 telegram.py

🐧 Linux / 🍎 macOS:
python3 telegram.py

Terminalde **📡 Bot çalışıyor...** yazısını görmelisin.


🤖 TELEGRAM BOT TOKEN NASIL ALINIR?

1️⃣ Telegram’da 👉 @BotFather’a gir  
2️⃣ `/start` yaz  
3️⃣ `/newbot` yaz  
4️⃣ Bot ismi ve kullanıcı adı belirle  
5️⃣ BotFather sana bir token verecek, örnek:

🔑 1234567890:AAH-R7vyraom5aDQrgkZEJJZ08Bc1XUJ-CY

Bu token’i 📂 `telegram.py` içindeki `BOT_TOKEN` değişkenine yapıştır.


🏥 MHRS GİRİŞ YÖNTEMLERİ

Bot iki farklı giriş yöntemini destekler 👇

🔐 1) Token ile giriş (kolay yöntem)

💻 Web üzerinden:
- https://www.mhrs.gov.tr adresine gir  
- F12 tuşuna bas  
- Network sekmesinden bir istek seç  
- Headers kısmında  
  Authorization: Bearer xxxxx  
  değerini bul  
- **Bearer** yazısını silip token’ı bot’a gönder  

📱 Mobil (HttpCanary):
- Telefonuna HttpCanary kur  
- MHRS mobil uygulamasında giriş yap  
- `/kurum-rss` içeren isteği bul  
- Authorization değerini kopyala  
- Bot’a gönder  

ℹ️ Not:
Token ile girişte token düşerse bot senden tekrar `/start` ister.

🪪 2) TC / Şifre ile giriş (önerilen yöntem ⭐)

Bu yöntemde bot MHRS’ye senin adına giriş yapar 🔐  
Token düşerse **401 hatasında otomatik olarak yeniler** 🔁  
5 kez denedikten sonra başarısız olursa ⏳ **60 dakika mola verir**.


🚀 KULLANIM

1️⃣ Telegram’da botu başlat:
/start

2️⃣ Giriş yöntemini seç:
1️⃣  Token ile giriş  
2️⃣  TC / Şifre ile giriş  

3️⃣ Sırasıyla seçim yap:
📍 İl plakası  
🏘️ İlçe  
🏥 Klinik  
⚙️ Mod:
   1️⃣ Otomatik al 🤖  
   2️⃣ Sadece bildir 📢  
📅 Tarih aralığı (gg.aa.yyyy)

4️⃣ Boş randevu bulununca:
📢 Bildirim modunda Telegram mesajı gelir  
🤖 Otomatik modda randevu alınır ve mesaj gelir  


⏱️ TARAMA MANTIĞI

Bot MHRS sistemini spamlamamak için insan benzeri çalışır 🧠

⏳ Her denemede 55–95 saniye rastgele bekler  
😴 En az 10 denemeden sonra %80 ihtimalle 5–10 dakika uzun mola verir  


📅 TARİH ARALIĞI (KAYAN PENCERE)

Kullanıcı bir tarih aralığı seçer (örn: 01.01.2026 – 10.01.2026).  
Bot bu aralığın gün farkını hesaplar 📊  
Her sorguda aralığı **bugünden itibaren kaydırarak** tarar ⏩  


🛠️ KOMUTLAR

/start   ➜ Yeni takip başlat 🚀  
/dur     ➜ Tüm takipleri durdur ⏹️  
/iptal   ➜ Devam eden seçim akışını iptal et ❌  
/yardim  ➜ Yardım / rehber 📘  


⚠️ OLASI HATALAR VE ÇÖZÜMLER

❌ Hata:
TypeError: AsyncClient.__init__() got an unexpected keyword argument 'proxies'

📌 Sebep:
python-telegram-bot ve httpx sürüm uyumsuzluğu.

✅ Çözüm:
pip install --force-reinstall httpx==0.27.0


👨‍💻 GELİŞTİRİCİ

Akın  
💻 GitHub: https://github.com/4kinn  


📌 SORUMLULUK REDDİ

Bu bot tamamen 🎓 **eğitim ve otomasyon amaçlıdır**.  
MHRS’nin resmi servisi değildir.  
Kullanım sorumluluğu kullanıcıya aittir.
