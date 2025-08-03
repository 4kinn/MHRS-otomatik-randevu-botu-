import asyncio
import requests
import logging
import os
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)

# Log ayarları
os.makedirs("logs", exist_ok=True)
user_logger = logging.getLogger("user_logger")
user_logger.setLevel(logging.INFO)
user_handler = logging.FileHandler(f"logs/{datetime.now().strftime('%Y-%m-%d')}.log", encoding="utf-8")
user_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
user_logger.addHandler(user_handler)

# Global değişkenler
aktif_kullanicilar = {}
TOKEN, BASLANGIC_TARIHI, BITIS_TARIHI, IL, ILCE, KLINIK, OTOMATIK = range(7)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Merhaba! MHRS Takip Botuna hoş geldin!\n\n"
        "🔐 *Lütfen MHRS token'ını gönder.*\n\n"
        "🛠 Komutlar:\n"
        "/start - Yeni takip başlat\n"
        "/dur - Tüm takipleri durdur\n"
        "/yardim - Token nasıl alınır ve nasıl kullanılır\n\n"
        "Destek için 📬 Telegram: @xAkinn0",
        parse_mode="Markdown"
    )
    return TOKEN

async def yardim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mesaj = (
        "📘 *MHRS Bot Yardım Rehberi*\n\n"
        "🔑 *Token Nedir?*\n"
        "Token, MHRS'ye giriş yaptıktan sonra oluşan oturum bilgisidir. Botun senin adına işlem yapabilmesi için bu gereklidir.\n\n"
        "📲 *Nasıl Token Alınır?*\n"
        "📱 *Mobil Uygulama (HttpCanary):*\n"
        "1. HttpCanary uygulamasını başlat\n"
        "2. MHRS mobil uygulamasına gir\n"
        "3. `/kurum-rss` içeren isteği bul\n"
        "4. *Authorization* kısmındaki değeri kopyala\n\n"
        "💻 *Web (Chrome Tarayıcı):*\n"
        "1. https://www.mhrs.gov.tr adresine gir ve giriş yap\n"
        "2. F12 ile geliştirici konsolunu aç\n"
        "3. Network sekmesine geç ve herhangi bir isteği seç\n"
        "4. Headers altında *Authorization* satırını kopyala\n\n"
        "ℹ️ *Notlar:*\n"
        "• Randevular her 10 dakika kontrol edilir.\n"
        "• Randevu bulunduğunda otomatik alınır veya bildirim gönderilir.\n\n"
        "📬 Destek: @xAkinn0"
    )
    await update.message.reply_text(mesaj, parse_mode="Markdown")

async def dur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or f"user_{uid}"

    if uid not in aktif_kullanicilar or not aktif_kullanicilar[uid]["takipler"]:
        await update.message.reply_text("❌ Aktif takip yok.")
        return ConversationHandler.END

    aktif_kullanicilar.pop(uid)
    await update.message.reply_text("⏹️ Tüm takipler durduruldu.")
    user_logger.info(f"{username} - Tüm takipleri durdurdu.")
    return ConversationHandler.END

async def get_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = update.message.text.strip().replace("Bearer ", "")
    context.user_data["token"] = token
    context.user_data["takipler"] = []
    uid = update.effective_user.id
    uname = update.effective_user.username

    user_logger.info(f"{uname} - Token girişi yapıldı: {token}")

    try:
        headers = {"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"}
        res = requests.get("https://prd.mhrs.gov.tr/api/vatandas/vatandas/hasta-bilgisi", headers=headers)

        if res.status_code == 200 and res.json().get("success"):
            data = res.json().get("data", {})
            ad = data.get("adi", "Bilinmiyor")
            soyad = data.get("soyadi", "Bilinmiyor")
            user_logger.info(f"{uname} - Hasta Bilgisi: {ad} {soyad}")
        else:
            user_logger.warning(f"{uname} - Hasta bilgisi alınamadı: {res.text}")
    except Exception as e:
        user_logger.warning(f"{uname} - Hasta bilgisi hatası: {e}")

    await update.message.reply_text("🌍 İl plakası girin (örn: 6 - Ankara):")
    return IL

async def get_il(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plaka = update.message.text.strip()
    token = context.user_data["token"]
    username = update.effective_user.username

    if not plaka.isdigit() or not (1 <= int(plaka) <= 81):
        await update.message.reply_text("❌ Geçerli plaka girin.")
        return IL

    context.user_data["il_id"] = plaka
    try:
        headers = {"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"}
        res = requests.get(f"https://prd.mhrs.gov.tr/api/yonetim/genel/ilce/selectinput/{plaka}", headers=headers)
        ilceler = res.json()
        context.user_data["ilceler"] = ilceler
        liste = "\n".join([f"{i+1} - {ilce['text']}" for i, ilce in enumerate(ilceler)])
        await update.message.reply_text("🏘 İlçe seç:\n" + liste)
        user_logger.info(f"{username} - İl seçimi yaptı: {plaka}")
        return ILCE
    except:
        await update.message.reply_text("⚠️ İlçe listesi alınamadı. Tokeni kontrol edin.")
        return IL

async def get_ilce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    try:
        secim = int(update.message.text.strip()) - 1
        ilce = context.user_data["ilceler"][secim]
        context.user_data["ilce_id"] = ilce["value"]
        context.user_data["ilce_adi"] = ilce["text"]
        user_logger.info(f"{username} - İlçe seçimi yaptı: {secim + 1}")
        il_id = context.user_data["il_id"]
        token = context.user_data["token"]
        headers = {"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"}
        res = requests.get(
            f"https://prd.mhrs.gov.tr/api/kurum/kurum/kurum-klinik/il/{il_id}/ilce/{ilce['value']}/kurum/-1/aksiyon/200/select-input",
            headers=headers
        )
        klinikler = res.json()["data"]
        context.user_data["klinikler"] = klinikler
        liste = "\n".join([f"{i+1} - {k['text']}" for i, k in enumerate(klinikler)])
        await update.message.reply_text("🏥 Klinik seç:\n" + liste)
        return KLINIK
    except:
        return ILCE

async def get_klinik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username

    try:
        secim = int(update.message.text.strip()) - 1
        klinik = context.user_data["klinikler"][secim]
        context.user_data["secilen_klinik"] = klinik
        user_logger.info(f"{username} - Klinik seçimi yaptı: {klinik['text']}")
    except:
        await update.message.reply_text("❌ Geçersiz seçim. Lütfen sayı girin.")
        return KLINIK

    await update.message.reply_text(
        "🔁 *Randevu Seçim Modu:*\n\n"
        "🤖 1 - Otomatik al (Randevu hemen alınır)\n"
        "📢 2 - Sadece bildir (Randevu bildirimi alırsınız)",
        parse_mode="Markdown"
    )
    return OTOMATIK

async def get_otomatik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    secim = update.message.text.strip()
    otomatik = secim == "1"
    uid = update.effective_user.id
    uname = update.effective_user.username or f"user_{uid}"

    context.user_data["otomatik"] = otomatik

    bugun = datetime.now().strftime("%d.%m.%Y")
    await update.message.reply_text(
        f"📅 *Başlangıç tarihi girin* (örn: {bugun}) veya /iptal ile iptal edin.",
        parse_mode="Markdown"
    )
    return BASLANGIC_TARIHI

async def get_baslangic_tarihi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        baslangic_tarihi = update.message.text.strip()
        datetime.strptime(baslangic_tarihi, "%d.%m.%Y")
        context.user_data["baslangic_tarihi"] = baslangic_tarihi
        onbes_gun_sonra = (datetime.now() + timedelta(days=15)).strftime("%d.%m.%Y")
        await update.message.reply_text(
            f"✅ Başlangıç tarihi seçildi: {baslangic_tarihi}\nŞimdi *bitiş tarihi* girin (örn: {onbes_gun_sonra}).",
            parse_mode="Markdown"
        )
        return BITIS_TARIHI
    except ValueError:
        await update.message.reply_text(
            "❌ Geçersiz tarih formatı. Lütfen gg.aa.yyyy formatında girin. Örnek: 25.04.2025.",
            parse_mode="Markdown"
        )
        return BASLANGIC_TARIHI

async def get_bitis_tarihi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bitis_tarihi = update.message.text.strip()
        datetime.strptime(bitis_tarihi, "%d.%m.%Y")
        context.user_data["bitis_tarihi"] = bitis_tarihi

        uid = update.effective_user.id
        uname = update.effective_user.username or f"user_{uid}"

        yeni_takip = {
            "il_id": context.user_data["il_id"],
            "ilce_id": context.user_data["ilce_id"],
            "klinik_id": context.user_data["secilen_klinik"]["value"],
            "klinik_adi": context.user_data["secilen_klinik"]["text"],
            "otomatik": context.user_data.get("otomatik", False),
            "token": context.user_data["token"],
            "baslangic_tarihi": context.user_data["baslangic_tarihi"],
            "bitis_tarihi": context.user_data["bitis_tarihi"],
        }

        aktif_kullanicilar.setdefault(uid, {"aktif": True, "takipler": []})
        aktif_kullanicilar[uid]["takipler"].append(yeni_takip)

        asyncio.create_task(takip_dongusu(uid, uname, context, yeni_takip))

        if context.user_data.get("otomatik"):
            await update.message.reply_text("✅ Takip eklendi. Otomatik randevu takibi başlatıldı.\nEkstra takip için /start komutunu kullanabilirsiniz.")
            user_logger.info(f"{uname} - Otomatik randevu takibi başlatıldı.")
        else:
            await update.message.reply_text("✅ Takip eklendi. Sadece bildirim takibi başlatıldı.\nEkstra takip için /start komutunu kullanabilirsiniz.")
            user_logger.info(f"{uname} - Bildirim takibi başlatıldı.")

        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text(
            "❌ Geçersiz tarih formatı. Lütfen gg.aa.yyyy formatında girin. Örnek: 30.04.2025.",
            parse_mode="Markdown"
        )
        return BITIS_TARIHI

async def takip_dongusu(user_id, username, context: ContextTypes.DEFAULT_TYPE, takip: dict):
    while True:
        if user_id not in aktif_kullanicilar:
            break
        if takip not in aktif_kullanicilar[user_id]["takipler"]:
            break

        sonuc = await randevu_sorgula(
            takip["token"],
            takip["il_id"],
            takip["ilce_id"],
            takip["klinik_id"],
            takip["klinik_adi"],
            username,
            user_id,
            context,
            takip["otomatik"],
            takip
        )
        if sonuc:
            aktif_kullanicilar[user_id]["takipler"].remove(takip)
            user_logger.info(f"{username} - Randevu sonrası takip sonlandırıldı: {takip['klinik_adi']}")
            break

        await asyncio.sleep(600)  # 10 dakika bekle

async def randevu_sorgula(token, il_id, ilce_id, klinik_id, klinik_adi, username, user_id, context, otomatik, takip):
    baslangic_tarihi = takip.get("baslangic_tarihi")
    bitis_tarihi = takip.get("bitis_tarihi")

    if not baslangic_tarihi or not bitis_tarihi:
        await context.bot.send_message(chat_id=user_id, text="⚠️ Tarih aralığı doğru seçilmedi. Lütfen geçerli tarih girin.")
        return

    try:
        baslangic_datetime = datetime.strptime(baslangic_tarihi, "%d.%m.%Y")
        bitis_datetime = datetime.strptime(bitis_tarihi, "%d.%m.%Y")
    except ValueError:
        await context.bot.send_message(chat_id=user_id, text="⚠️ Geçersiz tarih formatı. Lütfen gg.aa.yyyy formatında tarih girin.")
        return

    payload = {
        "aksiyonId": "200",
        "baslangicZamani": baslangic_datetime.strftime("%Y-%m-%d 08:00:00"),
        "bitisZamani": bitis_datetime.strftime("%Y-%m-%d 23:59:59"),
        "cinsiyet": "F",
        "ekRandevu": True,
        "mhrsHekimId": -1,
        "mhrsIlId": il_id,
        "mhrsIlceId": ilce_id,
        "mhrsKlinikId": klinik_id,
        "mhrsKurumId": -1,
        "muayeneYeriId": -1,
        "randevuZamaniList": [],
        "tumRandevular": False
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0"
    }

    try:
        res = requests.post("https://prd.mhrs.gov.tr/api/kurum-rss/randevu/slot-sorgulama/slot", headers=headers, json=payload)

        if res.status_code == 401:
            user_logger.warning(f"{username} - Token geçersiz, oturum sonlandı. (401)")
            mesaj = "❗ Token geçersiz, oturum sonlanmış. Lütfen tekrar giriş yapın ve token'ınızı gönderin."
            await context.bot.send_message(chat_id=user_id, text=mesaj, parse_mode="Markdown")
            return

        if res.status_code != 200:
            user_logger.warning(f"{username} - HTTP HATA {res.status_code} - {res.text}")
            return

        data = res.json().get("data", [])
        if not data:
            return

        for hekim in data[0].get("hekimSlotList", []):
            for muayene in hekim.get("muayeneYeriSlotList", []):
                for saat in muayene.get("saatSlotList", []):
                    for slot in saat.get("slotList", []):
                        if slot.get("bos"):
                            enriched = slot["slot"]
                            enriched.update({
                                "id": slot["id"],
                                "baslangicZamani": slot["baslangicZamani"],
                                "bitisZamani": slot["bitisZamani"],
                                "fkCetvelId": enriched.get("fkCetvelId"),
                                "muayeneYeriId": enriched.get("muayeneYeriId"),
                                "klinikAdi": klinik_adi
                            })

                            dt = datetime.fromisoformat(enriched['baslangicZamani'])
                            mesaj = (
                                f"📢 *Uygun Randevu Bulundu!*\n\n"
                                f"🏥 Klinik: `{klinik_adi}`\n"
                                f"📅 Tarih: *{dt.strftime('%d.%m.%Y')}*\n"
                                f"⏰ Saat: *{dt.strftime('%H:%M')}*\n\n"
                                f"⏹️ Takip bu randevudan sonra durduruldu. Yeni takip için /start yazabilirsin."
                            )

                            if otomatik:
                                basarili = await randevu_al(enriched, token, username, context, user_id)
                                return basarili
                            else:
                                await context.bot.send_message(chat_id=user_id, text=mesaj, parse_mode="Markdown")
                                return True
    except Exception as e:
        user_logger.warning(f"{username} - Randevu sorgulama hatası: {e}")

async def randevu_al(slot, token, username, context=None, user_id=None):
    url = "https://prd.mhrs.gov.tr/api/kurum/randevu/randevu-ekle"
    payload = {
        "fkSlotId": slot["id"],
        "fkCetvelId": slot["fkCetvelId"],
        "muayeneYeriId": slot.get("muayeneYeriId", -1),
        "yenidogan": False,
        "randevuNotu": "",
        "baslangicZamani": slot["baslangicZamani"],
        "bitisZamani": slot["bitisZamani"]
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    try:
        res = requests.post(url, headers=headers, json=payload)
        if res.status_code == 200 and res.json().get("success"):
            user_logger.info(f"{username} - RANDEVU ALINDI - {slot['baslangicZamani']}")
            if context and user_id:
                dt = datetime.fromisoformat(slot["baslangicZamani"])
                mesaj = (
                    f"✅ *Randevu Alındı!*\n\n"
                    f"🏥 Klinik: `{slot.get('klinikAdi', 'Bilinmiyor')}`\n"
                    f"📅 Tarih: *{dt.strftime('%d.%m.%Y')}*\n"
                    f"⏰ Saat: *{dt.strftime('%H:%M')}*\n\n"
                    f"⏹️ Takip bu randevudan sonra durduruldu. Yeni takip için /start yazabilirsin."
                )
                await context.bot.send_message(chat_id=user_id, text=mesaj, parse_mode="Markdown")
            return True
    except Exception as e:
        user_logger.warning(f"{username} - Randevu alma hatası: {e}")
    return False

def main():
    app = ApplicationBuilder().token("TOKENINI_BURAYA_YAZ").build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_token)],
            IL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_il)],
            ILCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_ilce)],
            KLINIK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_klinik)],
            OTOMATIK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_otomatik)],
            BASLANGIC_TARIHI: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_baslangic_tarihi)],
            BITIS_TARIHI: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_bitis_tarihi)],
        },
        fallbacks=[]
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("dur", dur))
    app.add_handler(CommandHandler("yardim", yardim))

    print("📡 Bot çalışıyor...")
    app.run_polling()

if __name__ == "__main__":
    main()
