import asyncio
import random
import re
import logging
import os
from datetime import datetime, timedelta

import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)

# ===========================
# Log ayarları
# ===========================
os.makedirs("logs", exist_ok=True)

logging.basicConfig(level=logging.INFO)

user_logger = logging.getLogger("user_logger")
user_logger.setLevel(logging.INFO)
user_handler = logging.FileHandler(
    f"logs/{datetime.now().strftime('%Y-%m-%d')}.log", encoding="utf-8"
)
user_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
user_logger.addHandler(user_handler)
user_logger.propagate = False

http_logger = logging.getLogger("http_logger")
http_logger.setLevel(logging.INFO)
http_handler = logging.FileHandler("logs/pc_log.txt", encoding="utf-8")
http_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
http_logger.addHandler(http_handler)
http_logger.propagate = False

# ===========================
# Global durum
# ===========================
aktif_kullanicilar = {}

# Takip döngüsü bekleme ayarları
WAIT_MIN = 55
WAIT_MAX = 95

LONG_BREAK_MIN_TRIES = 10
LONG_BREAK_PROB = 0.80
LONG_BREAK_SECONDS_MIN = 5 * 60
LONG_BREAK_SECONDS_MAX = 10 * 60

# Conversation states
AUTH_METHOD, TOKEN, TC, SIFRE, IL, ILCE, KLINIK, OTOMATIK, BASLANGIC_TARIHI, BITIS_TARIHI = range(10)

# ===========================
# Helpers (Core)
# ===========================
def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"}

def _strip_html(s: str) -> str:
    if not isinstance(s, str):
        return ""
    no_tags = re.sub(r"<.*?>", "", s)
    return no_tags.replace("\r", " ").replace("\n", " ").strip()

async def _http_get_json(url: str, headers: dict, timeout: int = 25):
    def _do():
        return requests.get(url, headers=headers, timeout=timeout)
    res = await asyncio.to_thread(_do)
    return res

async def _http_post_json(url: str, headers: dict, payload: dict, timeout: int = 25):
    def _do():
        return requests.post(url, headers=headers, json=payload, timeout=timeout)
    res = await asyncio.to_thread(_do)
    return res

async def mhrs_login_get_token(tc: str, sifre: str) -> str | None:
    """
    TC/Şifre ile MHRS login olur, JWT döner. Başarısızsa None.
    """
    url = "https://prd.mhrs.gov.tr/api/vatandas/login"
    payload = {
        "kullaniciAdi": tc,
        "parola": sifre,
        "islemKanali": "VATANDAS_WEB",
        "girisTipi": "PAROLA",
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Language": "tr-TR,tr;q=0.9",
    }
    try:
        res = await _http_post_json(url, headers=headers, payload=payload, timeout=20)
        if res.status_code != 200:
            http_logger.error("LOGIN HTTP %s - %s", res.status_code, res.text)
            return None
        js = res.json()
        jwt = (js or {}).get("data", {}).get("jwt")
        return jwt
    except Exception as e:
        http_logger.error("LOGIN EXC - %s", e)
        return None

# ===========================
# Commands
# ===========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Merhaba! MHRS Takip Botu\n\n"
        "Giriş yöntemi seç:\n"
        "1) Token ile\n"
        "2) TC/Şifre ile (401 olunca otomatik yeniler)\n\n"
        "Yanıt olarak 1 veya 2 yaz.\n\n"
        "🛠 Komutlar:\n"
        "/start - Yeni takip\n"
        "/dur - Tüm takipleri durdur\n"
        "/yardim - Token alma rehberi\n"
        "/iptal - İşlemi iptal\n\n"
        "Destek: @xAkinn0"
    )
    return AUTH_METHOD

async def yardim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mesaj = (
        "📘 *MHRS Bot Yardım Rehberi*\n\n"
        "🔑 *Token Nedir?*\n"
        "Token, MHRS'ye giriş yaptıktan sonra oluşan oturum bilgisidir.\n\n"
        "📲 *Nasıl Token Alınır?*\n"
        "📱 *Mobil (HttpCanary):*\n"
        "1. HttpCanary başlat\n"
        "2. MHRS mobil uygulamasına gir\n"
        "3. `/kurum-rss` içeren isteği bul\n"
        "4. Authorization değerini kopyala\n\n"
        "💻 *Web (Chrome):*\n"
        "1. mhrs.gov.tr giriş yap\n"
        "2. F12 → Network\n"
        "3. İstek seç → Headers → Authorization\n\n"
        "📌 Not: TC/Şifre ile girersen token düşse bile bot otomatik yeniler.\n"
        "📬 Destek: @xAkinn0"
    )
    await update.message.reply_text(mesaj, parse_mode="Markdown")

async def iptal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ İptal edildi. Tekrar başlamak için /start.")
    return ConversationHandler.END

async def dur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or f"user_{uid}"

    if uid not in aktif_kullanicilar or not aktif_kullanicilar[uid].get("takipler"):
        await update.message.reply_text("❌ Aktif takip yok.")
        return ConversationHandler.END

    aktif_kullanicilar.pop(uid, None)
    await update.message.reply_text("⏹️ Tüm takipler durduruldu.")
    user_logger.info(f"{username} - Tüm takipleri durdurdu.")
    return ConversationHandler.END

# ===========================
# Conversation steps
# ===========================
async def get_auth_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sel = update.message.text.strip()
    if sel not in ("1", "2"):
        await update.message.reply_text("❌ 1 veya 2 yaz kanka.")
        return AUTH_METHOD

    context.user_data["auth_method"] = sel
    if sel == "1":
        await update.message.reply_text("🔐 MHRS token'ını gönder (Bearer yazmadan).")
        return TOKEN
    else:
        await update.message.reply_text("🪪 TC Kimlik No (11 hane) gönder.")
        return TC

async def get_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = update.message.text.strip().replace("Bearer ", "")
    context.user_data["token"] = token

    uid = update.effective_user.id
    uname = update.effective_user.username or f"user_{uid}"
    user_logger.info(f"{uname} - Token girişi yapıldı.")

    # Hasta bilgisi dene
    try:
        res = await _http_get_json(
            "https://prd.mhrs.gov.tr/api/vatandas/vatandas/hasta-bilgisi",
            headers=_headers(token),
            timeout=20
        )
        if res.status_code == 200 and res.json().get("success"):
            data = res.json().get("data", {})
            ad = data.get("adi", "Bilinmiyor")
            soyad = data.get("soyadi", "Bilinmiyor")
            user_logger.info(f"{uname} - Hasta Bilgisi: {ad} {soyad}")
    except Exception as e:
        user_logger.warning(f"{uname} - Hasta bilgisi hatası: {e}")

    await update.message.reply_text("🌍 İl plakası girin (1-81). Örn: 34")
    return IL

async def get_tc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tc = update.message.text.strip()
    if not (tc.isdigit() and len(tc) == 11):
        await update.message.reply_text("❌ TC 11 haneli olmalı. Tekrar gönder.")
        return TC
    context.user_data["tc"] = tc
    await update.message.reply_text("🔑 MHRS şifreyi gönder.")
    return SIFRE

async def get_sifre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sifre = update.message.text.strip()
    tc = context.user_data.get("tc")
    uname = update.effective_user.username or f"user_{update.effective_user.id}"

    await update.message.reply_text("⏳ Giriş yapıyorum...")
    jwt = await mhrs_login_get_token(tc, sifre)
    if not jwt:
        user_logger.warning(f"{uname} - TC/Şifre login başarısız.")
        await update.message.reply_text("❌ Giriş başarısız. /start ile tekrar dene.")
        return ConversationHandler.END

    context.user_data["sifre"] = sifre
    context.user_data["token"] = jwt
    user_logger.info(f"{uname} - TC/Şifre login başarılı, token alındı.")
    await update.message.reply_text("✅ Giriş tamam. 🌍 İl plakası girin (1-81). Örn: 34")
    return IL

async def get_il(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plaka = update.message.text.strip()
    token = context.user_data["token"]
    username = update.effective_user.username or f"user_{update.effective_user.id}"

    if not plaka.isdigit() or not (1 <= int(plaka) <= 81):
        await update.message.reply_text("❌ Geçerli plaka girin.")
        return IL

    context.user_data["il_id"] = plaka
    try:
        res = await _http_get_json(
            f"https://prd.mhrs.gov.tr/api/yonetim/genel/ilce/selectinput/{plaka}",
            headers=_headers(token),
            timeout=25
        )
        ilceler = res.json()
        context.user_data["ilceler"] = ilceler
        liste = "\n".join([f"{i+1} - {ilce['text']}" for i, ilce in enumerate(ilceler)])
        await update.message.reply_text("🏘 İlçe seç:\n" + liste)
        user_logger.info(f"{username} - İl seçimi: {plaka}")
        return ILCE
    except Exception as e:
        user_logger.warning(f"{username} - İlçe listesi hatası: {e}")
        await update.message.reply_text("⚠️ İlçe listesi alınamadı. Tokeni kontrol et.")
        return IL

async def get_ilce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or f"user_{update.effective_user.id}"
    try:
        secim = int(update.message.text.strip()) - 1
        ilce = context.user_data["ilceler"][secim]
    except Exception:
        await update.message.reply_text("❌ Geçersiz seçim. İlçe için sayı gir.")
        return ILCE

    context.user_data["ilce_id"] = ilce["value"]
    context.user_data["ilce_adi"] = ilce["text"]
    user_logger.info(f"{username} - İlçe seçimi: {ilce['text']}")

    il_id = context.user_data["il_id"]
    token = context.user_data["token"]
    try:
        res = await _http_get_json(
            f"https://prd.mhrs.gov.tr/api/kurum/kurum/kurum-klinik/il/{il_id}/ilce/{ilce['value']}/kurum/-1/aksiyon/200/select-input",
            headers=_headers(token),
            timeout=25
        )
        klinikler = res.json()["data"]
        context.user_data["klinikler"] = klinikler
        liste = "\n".join([f"{i+1} - {k['text']}" for i, k in enumerate(klinikler)])
        await update.message.reply_text("🏥 Klinik seç:\n" + liste)
        return KLINIK
    except Exception as e:
        user_logger.warning(f"{username} - Klinik listesi hatası: {e}")
        await update.message.reply_text("⚠️ Klinik listesi alınamadı. /start ile yeniden dene.")
        return ConversationHandler.END

async def get_klinik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or f"user_{update.effective_user.id}"
    try:
        secim = int(update.message.text.strip()) - 1
        klinik = context.user_data["klinikler"][secim]
        context.user_data["secilen_klinik"] = klinik
        user_logger.info(f"{username} - Klinik seçimi: {klinik['text']}")
    except Exception:
        await update.message.reply_text("❌ Geçersiz seçim. Klinik için sayı gir.")
        return KLINIK

    await update.message.reply_text(
        "🔁 *Randevu Seçim Modu:*\n\n"
        "🤖 1 - Otomatik al\n"
        "📢 2 - Sadece bildir",
        parse_mode="Markdown"
    )
    return OTOMATIK

async def get_otomatik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    secim = update.message.text.strip()
    if secim not in ("1", "2"):
        await update.message.reply_text("❌ 1 veya 2 yaz.")
        return OTOMATIK

    otomatik = (secim == "1")
    context.user_data["otomatik"] = otomatik

    bugun = datetime.now().strftime("%d.%m.%Y")
    onbes = (datetime.now() + timedelta(days=15)).strftime("%d.%m.%Y")

    await update.message.reply_text(
        f"📅 Başlangıç tarihi gir (gg.aa.yyyy). Örn: {bugun}\n"
        f"Not: Bot bu aralığın gün farkını alıp her seferinde bugünden itibaren kayan pencere tarar.",
    )
    context.user_data["default_bit"] = onbes
    return BASLANGIC_TARIHI

async def get_baslangic_tarihi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bas = update.message.text.strip()
    try:
        datetime.strptime(bas, "%d.%m.%Y")
    except ValueError:
        await update.message.reply_text("❌ Format yanlış. gg.aa.yyyy örn: 25.04.2025")
        return BASLANGIC_TARIHI

    context.user_data["baslangic_tarihi"] = bas
    await update.message.reply_text(
        f"✅ Başlangıç: {bas}\n"
        f"Şimdi bitiş tarihi gir (gg.aa.yyyy). Örn: {context.user_data['default_bit']}"
    )
    return BITIS_TARIHI

async def get_bitis_tarihi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bit = update.message.text.strip()
    try:
        datetime.strptime(bit, "%d.%m.%Y")
    except ValueError:
        await update.message.reply_text("❌ Format yanlış. gg.aa.yyyy örn: 30.04.2025")
        return BITIS_TARIHI

    context.user_data["bitis_tarihi"] = bit

    uid = update.effective_user.id
    uname = update.effective_user.username or f"user_{uid}"

    takip = {
        "il_id": context.user_data["il_id"],
        "ilce_id": context.user_data["ilce_id"],
        "klinik_id": context.user_data["secilen_klinik"]["value"],
        "klinik_adi": context.user_data["secilen_klinik"]["text"],
        "otomatik": context.user_data.get("otomatik", False),
        "token": context.user_data["token"],
        "baslangic_tarihi": context.user_data["baslangic_tarihi"],
        "bitis_tarihi": context.user_data["bitis_tarihi"],
        # opsiyonel: 401 yenilemek için
        "tc": context.user_data.get("tc"),
        "sifre": context.user_data.get("sifre"),
        "hekim_id": -1,
        "kurum_id": -1,
        "hekim_adi": "Farketmez",
        "kurum_adi": "Farketmez",
    }

    aktif_kullanicilar.setdefault(uid, {"aktif": True, "takipler": []})
    aktif_kullanicilar[uid]["takipler"].append(takip)

    asyncio.create_task(takip_dongusu(uid, uname, context, takip))

    if takip["otomatik"]:
        await update.message.reply_text(
            "✅ Takip eklendi. 🤖 Otomatik randevu takibi başladı.\n"
            "Durdurmak için /dur"
        )
    else:
        await update.message.reply_text(
            "✅ Takip eklendi. 📢 Bildirim modu başladı.\n"
            "Durdurmak için /dur"
        )

    user_logger.info(f"{uname} - Takip eklendi: {takip['klinik_adi']} (otomatik={takip['otomatik']})")
    return ConversationHandler.END

# ===========================
# Core: Takip + Sorgu + Alım
# ===========================
async def randevu_al(slot, token, username, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    url = "https://prd.mhrs.gov.tr/api/kurum/randevu/randevu-ekle"
    payload = {
        "fkSlotId": slot["id"],
        "fkCetvelId": slot["fkCetvelId"],
        "muayeneYeriId": slot.get("muayeneYeriId", -1),
        "yenidogan": False,
        "randevuNotu": "",
        "baslangicZamani": slot["baslangicZamani"],
        "bitisZamani": slot["bitisZamani"],
    }

    try:
        res = await _http_post_json(url, headers=_headers(token), payload=payload, timeout=20)
        http_ok = (res.status_code == 200)

        try:
            js = res.json()
        except Exception:
            js = None

        # varsayılanlar
        dt = datetime.fromisoformat(slot["baslangicZamani"])
        klinik_adi = slot.get("klinikAdi", "Bilinmiyor")
        hekim_adi = slot.get("hekimAdi", "Bilinmiyor")
        muayene_yeri = slot.get("muayeneYeriAdi") or slot.get("muayeneYeriId", "-")

        # cevap içinden güzelleştir
        if js:
            data = js.get("data", {}) or {}
            hekim_info = data.get("hekim") or {}
            ad = (hekim_info.get("ad") or "").strip()
            soyad = (hekim_info.get("soyad") or "").strip()
            full_name = (ad + " " + soyad).strip()
            if full_name:
                hekim_adi = full_name

            klinik_info = data.get("klinik") or {}
            klinik_adi_resp = (klinik_info.get("mhrsKlinikAdi") or klinik_info.get("kisaAdi") or "").strip()
            if klinik_adi_resp:
                klinik_adi = klinik_adi_resp

            muayene_info = data.get("muayeneYeri") or {}
            muayene_yeri_adi = (muayene_info.get("adi") or "").strip()
            if muayene_yeri_adi:
                muayene_yeri = muayene_yeri_adi

        ok = http_ok and ((js or {}).get("success", True))
        if ok:
            user_logger.info(
                f"{username} - RANDEVU ALINDI | Klinik:{klinik_adi} | Hekim:{hekim_adi} | "
                f"MuayeneYeri:{muayene_yeri} | {dt.strftime('%d.%m.%Y %H:%M')} | SlotId:{slot.get('id')}"
            )
            mesaj = (
                "✅ *Randevu Alındı!*\n\n"
                f"🏥 Klinik: `{klinik_adi}`\n"
                f"👨‍⚕️ Hekim: `{hekim_adi}`\n"
                f"📍 Muayene Yeri: `{muayene_yeri}`\n"
                f"📅 Tarih: *{dt.strftime('%d.%m.%Y')}*\n"
                f"⏰ Saat: *{dt.strftime('%H:%M')}*\n\n"
                "⏹️ Bu takip durduruldu. Yeni takip için /start"
            )
            await context.bot.send_message(chat_id=user_id, text=mesaj, parse_mode="Markdown")
            return True

        http_logger.error("RANDEVU_EKLE HTTP %s - %s", res.status_code, res.text)
        user_logger.warning(f"{username} - Randevu alma BAŞARISIZ - {res.status_code}")
        return False

    except Exception as e:
        user_logger.warning(f"{username} - Randevu alma hatası: {e}")
        return False

async def randevu_sorgula(takip: dict, username: str, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    token = takip["token"]
    il_id = takip["il_id"]
    ilce_id = takip["ilce_id"]
    klinik_id = takip["klinik_id"]
    klinik_adi = takip["klinik_adi"]
    otomatik = takip["otomatik"]

    # ----- Kayan pencere -----
    orj_bas = takip.get("baslangic_tarihi")
    orj_bit = takip.get("bitis_tarihi")
    try:
        orj_bas_dt = datetime.strptime(orj_bas, "%d.%m.%Y") if orj_bas else None
        orj_bit_dt = datetime.strptime(orj_bit, "%d.%m.%Y") if orj_bit else None
        gun_farki = max(0, (orj_bit_dt - orj_bas_dt).days) if (orj_bas_dt and orj_bit_dt) else 15
    except Exception:
        gun_farki = 15

    bugun = datetime.now()
    bas_dt = bugun.replace(hour=0, minute=0, second=0, microsecond=0)
    bit_dt = bas_dt + timedelta(days=gun_farki)

    payload = {
        "aksiyonId": "200",
        "baslangicZamani": bas_dt.strftime("%Y-%m-%d 08:00:00"),
        "bitisZamani": bit_dt.strftime("%Y-%m-%d 23:59:59"),
        "cinsiyet": "F",
        "ekRandevu": True,
        "mhrsHekimId": takip.get("hekim_id", -1),
        "mhrsIlId": il_id,
        "mhrsIlceId": ilce_id,
        "mhrsKlinikId": klinik_id,
        "mhrsKurumId": takip.get("kurum_id", -1),
        "muayeneYeriId": -1,
        "randevuZamaniList": [],
        "tumRandevular": False,
    }

    url = "https://prd.mhrs.gov.tr/api/kurum-rss/randevu/slot-sorgulama/slot"

    res = await _http_post_json(url, headers=_headers(token), payload=payload, timeout=25)

    # 401 -> TC/Şifre varsa otomatik yenile
    if res.status_code == 401:
        user_logger.warning(f"{username} - Token geçersiz (401). Yenileme denenecek.")
        if not (takip.get("tc") and takip.get("sifre")):
            await context.bot.send_message(
                chat_id=user_id,
                text="❗ Token geçersiz (401) ve TC/Şifre yok. /start ile tekrar giriş yap."
            )
            return False

        await context.bot.send_message(chat_id=user_id, text="⚠️ Oturum düştü. Token yenilemeye çalışıyorum...")

        max_retry = 5
        for deneme in range(1, max_retry + 1):
            new_jwt = await mhrs_login_get_token(takip["tc"], takip["sifre"])
            if new_jwt:
                takip["token"] = new_jwt
                token = new_jwt
                user_logger.info(f"{username} - Oturum yenilendi.")
                await context.bot.send_message(chat_id=user_id, text="✅ Oturum yenilendi. Tarama devam ediyor...")

                res = await _http_post_json(url, headers=_headers(token), payload=payload, timeout=25)
                break

            if deneme < max_retry:
                wait = random.randint(30, 90)
                await asyncio.sleep(wait)

        if res.status_code == 401:
            mola = 3600
            user_logger.warning(f"{username} - 5 yenileme denemesi başarısız. 60 dk mola.")
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ 5 kez yeniden giriş denemesi başarısız. 60 dakika mola veriyorum."
            )
            await asyncio.sleep(mola)
            return False

    # JSON parse
    try:
        js = res.json()
    except Exception:
        js = {}

    if res.status_code != 200:
        http_logger.error("SLOT HTTP %s - %s", res.status_code, res.text)

        warnings_list = js.get("warnings") or []
        if warnings_list and isinstance(warnings_list, list):
            w0 = warnings_list[0] or {}
            kodu = w0.get("kodu", "BILINMIYOR")
            mesaj_plain = _strip_html(w0.get("mesaj", ""))
            user_logger.info(f"{username} - MHRS UYARI | Kod: {kodu} | Mesaj: {mesaj_plain}")
        else:
            user_logger.warning(f"{username} - Slot sorgusu başarısız: HTTP {res.status_code}")
        return False

    data = (js or {}).get("data", [])
    warnings_list = (js or {}).get("warnings") or []

    if not data:
        if warnings_list and isinstance(warnings_list, list):
            w0 = warnings_list[0] or {}
            kodu = w0.get("kodu", "BILINMIYOR")
            mesaj_plain = _strip_html(w0.get("mesaj", ""))
            user_logger.info(f"{username} - MHRS UYARI | Kod: {kodu} | Mesaj: {mesaj_plain}")
        return False

    # Slot tarama: hekim adını data ağacından çek
    for hekim in data[0].get("hekimSlotList", []):
        hekim_info = hekim.get("hekim") or hekim
        ad = (hekim_info.get("ad") or "").strip()
        soyad = (hekim_info.get("soyad") or "").strip()
        hekim_adi = (ad + " " + soyad).strip() or (
            hekim_info.get("hekimAdi")
            or hekim_info.get("hekimAd")
            or hekim_info.get("hekimAdiSoyadi")
            or hekim_info.get("text")
            or "Bilinmiyor"
        )

        for muayene in hekim.get("muayeneYeriSlotList", []):
            for saat in muayene.get("saatSlotList", []):
                for sl in saat.get("slotList", []):
                    if not sl.get("bos"):
                        continue

                    enriched = sl["slot"]
                    enriched.update({
                        "id": sl["id"],
                        "baslangicZamani": sl["baslangicZamani"],
                        "bitisZamani": sl["bitisZamani"],
                        "fkCetvelId": enriched.get("fkCetvelId"),
                        "muayeneYeriId": enriched.get("muayeneYeriId"),
                        "klinikAdi": klinik_adi,
                        "hekimAdi": hekim_adi,
                    })

                    dt = datetime.fromisoformat(enriched["baslangicZamani"])
                    if dt <= datetime.now():
                        continue

                    if otomatik:
                        return await randevu_al(enriched, token, username, context, user_id)

                    mesaj = (
                        "📢 *Uygun Randevu Bulundu!*\n\n"
                        f"🏥 Klinik: `{klinik_adi}`\n"
                        f"👨‍⚕️ Hekim: `{hekim_adi}`\n"
                        f"📅 Tarih: *{dt.strftime('%d.%m.%Y')}*\n"
                        f"⏰ Saat: *{dt.strftime('%H:%M')}*\n\n"
                        "⏹️ Bu takip durduruldu. Yeni takip için /start"
                    )
                    await context.bot.send_message(chat_id=user_id, text=mesaj, parse_mode="Markdown")
                    return True

    return False

async def takip_dongusu(user_id: int, username: str, context: ContextTypes.DEFAULT_TYPE, takip: dict):
    deneme = 0
    since_long_break = 0

    while True:
        if user_id not in aktif_kullanicilar:
            break
        if takip not in aktif_kullanicilar[user_id]["takipler"]:
            break

        sonuc = await randevu_sorgula(takip, username, user_id, context)

        if sonuc:
            try:
                aktif_kullanicilar[user_id]["takipler"].remove(takip)
            except ValueError:
                pass
            user_logger.info(f"{username} - Randevu sonrası takip sonlandırıldı: {takip['klinik_adi']}")
            break

        deneme += 1
        since_long_break += 1

        uzun_mola = False
        if since_long_break >= LONG_BREAK_MIN_TRIES:
            if random.random() < LONG_BREAK_PROB:
                uzun_mola = True

        if uzun_mola:
            uzun_bekleme = random.randint(LONG_BREAK_SECONDS_MIN, LONG_BREAK_SECONDS_MAX)
            dakika = uzun_bekleme // 60
            saniye = uzun_bekleme % 60

            user_logger.info(f"{username} - {deneme}. deneme sonrası uzun mola: {dakika}dk {saniye}sn")
            await context.bot.send_message(
                chat_id=user_id,
                text=f"😴 {deneme}. deneme sonrası uzun mola: {dakika} dk {saniye} sn"
            )

            since_long_break = 0
            await asyncio.sleep(uzun_bekleme)
            continue

        bekleme = random.randint(WAIT_MIN, WAIT_MAX)
        user_logger.info(f"{username} - {bekleme} saniye bekleniyor (deneme #{deneme})")
        await asyncio.sleep(bekleme)

# ===========================
# Main
# ===========================
def main():
    BOT_TOKEN = "TOKENINI_BURAYA_YAZ"

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            AUTH_METHOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_auth_method)],
            TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_token)],
            TC: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_tc)],
            SIFRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_sifre)],
            IL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_il)],
            ILCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_ilce)],
            KLINIK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_klinik)],
            OTOMATIK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_otomatik)],
            BASLANGIC_TARIHI: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_baslangic_tarihi)],
            BITIS_TARIHI: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_bitis_tarihi)],
        },
        fallbacks=[
            CommandHandler("iptal", iptal),
            CommandHandler("dur", dur),
        ],
        allow_reentry=True
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("dur", dur))
    app.add_handler(CommandHandler("yardim", yardim))
    app.add_handler(CommandHandler("iptal", iptal))

    print("📡 Bot çalışıyor...")
    app.run_polling()

if __name__ == "__main__":
    main()
