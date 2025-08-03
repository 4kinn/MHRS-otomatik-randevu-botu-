# mhrs_pc.py
import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timedelta
import argparse

import requests

# ===========================
# Log Ayarları (PC Modu)
# ===========================
os.makedirs("logs", exist_ok=True)

logging.basicConfig(level=logging.INFO)  # konsola INFO akıtır
user_logger = logging.getLogger("user_logger")
user_logger.setLevel(logging.INFO)
user_handler = logging.FileHandler(
    f"logs/{datetime.now().strftime('%Y-%m-%d')}.log", encoding="utf-8"
)
user_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
user_logger.addHandler(user_handler)
user_logger.propagate = False
http_logger = logging.getLogger("httpx")
http_logger.setLevel(logging.INFO)
http_handler = logging.FileHandler("logs/pc_log.txt", encoding="utf-8")
http_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
http_logger.addHandler(http_handler)

# ===========================
# Global Durum
# ===========================
# (PC modunda tek kullanıcı senaryosu; yine de yapı korunuyor)
AUTH_METHOD, TOKEN, TC_STATE, SIFRE_STATE, BASLANGIC_TARIHI, BITIS_TARIHI, IL, ILCE, KLINIK, HEKIM, KURUM, OTOMATIK = range(
    12
)
aktif_kullanicilar = {}

# ===========================
# Yardımcılar
# ===========================
def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"}

def mhrs_login_get_token(tc: str, sifre: str) -> str | None:
    """
    TC/Şifre ile MHRS login olur, JWT döner. Başarısızsa None.
    Konsola basit debug çıktısı verir.
    """
    try:
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

        print("⏳ MHRS API’ye istek atılıyor (login)...")
        res = requests.post(url, json=payload, headers=headers, timeout=20)

        print(f"📡 HTTP Kod: {res.status_code}")
        try:
            js = res.json()
            print("Giriş başarılı.")
        except Exception:
            js = None
            print("⚠️ Giriş başaarısız:", res.text)

        if res.status_code != 200:
            return None

        jwt = (js or {}).get("data", {}).get("jwt")
        return jwt
    except Exception as e:
        print(f"🚨 Hata (login): {e}")
        return None

def _select_from_list(prompt_title, options):
    """
    options: [{'value':.., 'text':..}, ...] veya string listesi
    return: seçilen öğe (dict veya string)
    """
    print("\n" + prompt_title)
    for i, opt in enumerate(options, 1):
        label = opt["text"] if isinstance(opt, dict) and "text" in opt else str(opt)
        print(f"{i}) {label}")
    while True:
        secim = input("Seçimin (sayı): ").strip()
        if secim.isdigit():
            idx = int(secim) - 1
            if 0 <= idx < len(options):
                return options[idx]
        print("❌ Geçersiz seçim. Tekrar dene.")

def _input_date(prompt_text, default=None):
    while True:
        val = input(f"{prompt_text}{' ['+default+']' if default else ''}: ").strip()
        if not val and default:
            val = default
        try:
            datetime.strptime(val, "%d.%m.%Y")
            return val
        except Exception:
            print("❌ Geçersiz tarih. Format: gg.aa.yyyy")

# ===========================
# Çekirdek İşlevler
# ===========================
async def randevu_al(slot, token, username, user_id=1):
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
        res = requests.post(url, headers=_headers(token), json=payload, timeout=20)
        ok = res.status_code == 200 and (res.json() or {}).get("success")
        dt = datetime.fromisoformat(slot["baslangicZamani"])
        if ok:
            user_logger.info(f"{username} - RANDEVU ALINDI - {slot['baslangicZamani']}")
            print("\n" + "—" * 40)
            print("✅ Randevu Alındı!")
            print(f"🏥 Klinik: {slot.get('klinikAdi', 'Bilinmiyor')}")
            print(f"📅 Tarih: {dt.strftime('%d.%m.%Y')}")
            print(f"⏰ Saat:  {dt.strftime('%H:%M')}")
            print("—" * 40 + "\n")
            return True
        else:
            user_logger.warning(
                f"{username} - Randevu alma BAŞARISIZ - {res.status_code} - {res.text}"
            )
    except Exception as e:
        user_logger.warning(f"{username} - Randevu alma hatası: {e}")
    return False

async def randevu_sorgula(takip: dict, username="pc_user", user_id=1):
    """
    Uygun slot arar; otomatikse randevu almaya çalışır, değilse bildirir.
    takip dict: token, il/ilce/klinik/kurum/hekim ve tarih aralığı
    """
    token = takip["token"]
    il_id = takip["il_id"]
    ilce_id = takip["ilce_id"]
    klinik_id = takip["klinik_id"]
    klinik_adi = takip["klinik_adi"]
    otomatik = takip["otomatik"]

    baslangic_tarihi = takip.get("baslangic_tarihi")
    bitis_tarihi = takip.get("bitis_tarihi")

    if not baslangic_tarihi or not bitis_tarihi:
        print("⚠️ Tarih aralığı eksik.")
        return

    try:
        baslangic_datetime = datetime.strptime(baslangic_tarihi, "%d.%m.%Y")
        bitis_datetime = datetime.strptime(bitis_tarihi, "%d.%m.%Y")
    except ValueError:
        print("⚠️ Geçersiz tarih formatı (gg.aa.yyyy).")
        return

    payload = {
        "aksiyonId": "200",
        "baslangicZamani": baslangic_datetime.strftime("%Y-%m-%d 08:00:00"),
        "bitisZamani": bitis_datetime.strftime("%Y-%m-%d 23:59:59"),
        "cinsiyet": "F",  # ihtiyaca göre kullanıcıdan alınabilir
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

    try:
        res = requests.post(
            "https://prd.mhrs.gov.tr/api/kurum-rss/randevu/slot-sorgulama/slot",
            headers=_headers(token),
            json=payload,
            timeout=25,
        )

        # 401 → otomatik login denenebilir (takip['tc'] ve ['sifre'] varsa)
        if res.status_code == 401:
            user_logger.warning(f"{username} - Token geçersiz (401).")
            if takip.get("tc") and takip.get("sifre"):
                new_jwt = mhrs_login_get_token(takip["tc"], takip["sifre"])
                if new_jwt:
                    takip["token"] = new_jwt
                    token = new_jwt
                    res = requests.post(
                        "https://prd.mhrs.gov.tr/api/kurum-rss/randevu/slot-sorgulama/slot",
                        headers=_headers(new_jwt),
                        json=payload,
                        timeout=25,
                    )
                else:
                    print("❗ Oturum süresi doldu, otomatik yenileme başarısız. Tekrar giriş yapın.")
                    return
            else:
                print("❗ Token geçersiz. Tekrar giriş yapın.")
                return

        if res.status_code != 200:
            user_logger.warning(f"{username} - HTTP HATA {res.status_code} - {res.text}")
            return

        data = (res.json() or {}).get("data", [])
        if not data:
            return

        # İlk hekim ağaç yapısından boş slot ara
        for hekim in data[0].get("hekimSlotList", []):
            for muayene in hekim.get("muayeneYeriSlotList", []):
                for saat in muayene.get("saatSlotList", []):
                    for sl in saat.get("slotList", []):
                        if sl.get("bos"):
                            enriched = sl["slot"]
                            enriched.update(
                                {
                                    "id": sl["id"],
                                    "baslangicZamani": sl["baslangicZamani"],
                                    "bitisZamani": sl["bitisZamani"],
                                    "fkCetvelId": enriched.get("fkCetvelId"),
                                    "muayeneYeriId": enriched.get("muayeneYeriId"),
                                    "klinikAdi": klinik_adi,
                                }
                            )

                            # Geçmiş slotları ele
                            randevu_zamani = datetime.fromisoformat(enriched["baslangicZamani"])
                            if randevu_zamani <= datetime.now():
                                continue

                            if otomatik:
                                basarili = await randevu_al(enriched, token, username, user_id)
                                return basarili
                            else:
                                dt = randevu_zamani
                                print("\n" + "—" * 40)
                                print("📢 Uygun Randevu Bulundu!")
                                print(f"🏥 Klinik: {klinik_adi}")
                                print(f"📅 Tarih: {dt.strftime('%d.%m.%Y')}")
                                print(f"⏰ Saat:  {dt.strftime('%H:%M')}")
                                print("—" * 40 + "\n")
                                return True
    except Exception as e:
        user_logger.warning(f"{username} - Randevu sorgulama hatası: {e}")

async def takip_dongusu(user_id, username, takip: dict):
    """
    Antiban mantığı: 60–120 sn random bekleme; her 10 denemede 5–10 dk mola.
    Slot bulunduğunda takip sonlandırılır.
    """
    deneme = 0
    while True:
        if user_id not in aktif_kullanicilar:
            break
        if takip not in aktif_kullanicilar[user_id]["takipler"]:
            break

        sonuc = await randevu_sorgula(takip, username, user_id)
        if sonuc:
            aktif_kullanicilar[user_id]["takipler"].remove(takip)
            user_logger.info(
                f"{username} - Randevu sonrası takip sonlandırıldı: {takip['klinik_adi']}"
            )
            break

    deneme += 1
    bekleme = random.randint(60, 120)  # 60-120 sn arası bekle

    if deneme % 10 == 0:
        uzun_ara = random.randint(300, 600)  # 5-10 dk mola
        user_logger.info(f"{username} - 10 deneme, {uzun_ara//60} dk mola")
        print(f"ℹ️ Randevu bulunamadı. {uzun_ara//60} dakika mola veriliyor, sonra tekrar denenecek...")
        await asyncio.sleep(uzun_ara)
    else:
        user_logger.info(f"{username} - {bekleme} saniye bekleniyor")
        print(f"ℹ️ Randevu bulunamadı. {bekleme} saniye sonra tekrar denenecek...")
        await asyncio.sleep(bekleme)

# ===========================
# PC Modu (Konsol Sihirbaz)
# ===========================
def main_pc():
    print("💻 PC Modu – MHRS Takip Sihirbazı\n")

    # Giriş yöntemi
    print("Giriş yöntemi: 1) Token  2) TC/Şifre")
    while True:
        am = input("Seçimin (1/2): ").strip()
        if am in ("1", "2"):
            break
        print("❌ 1 veya 2 gir.")
    token = None
    tc = None
    sifre = None

    if am == "1":
        token = input("Authorization (Bearer ... yazmadan JWT): ").strip().replace("Bearer ", "")
    else:
        tc = input("TC Kimlik No (11 hane): ").strip()
        sifre = input("MHRS Şifre: ").strip()
        jwt = mhrs_login_get_token(tc, sifre)
        if not jwt:
            print("❌ Giriş başarısız. Çıkılıyor.")
            return
        token = jwt

    # İl (plaka)
    while True:
        plaka = input("İl plakası (1-81): ").strip()
        if plaka.isdigit() and 1 <= int(plaka) <= 81:
            break
        print("❌ Geçersiz plaka.")

    # İlçe listesi
    try:
        ilceler = requests.get(
            f"https://prd.mhrs.gov.tr/api/yonetim/genel/ilce/selectinput/{plaka}",
            headers=_headers(token),
            timeout=25,
        ).json()
    except Exception as e:
        print(f"❌ İlçe listesi alınamadı: {e}")
        return

    ilce = _select_from_list("🏘 İlçe seç:", ilceler)
    il_id = plaka
    ilce_id = ilce["value"]
    ilce_adi = ilce["text"]

    # Klinik listesi
    try:
        klinikler = requests.get(
            f"https://prd.mhrs.gov.tr/api/kurum/kurum/kurum-klinik/il/{il_id}/ilce/{ilce_id}/kurum/-1/aksiyon/200/select-input",
            headers=_headers(token),
            timeout=25,
        ).json()["data"]
    except Exception as e:
        print(f"❌ Klinik listesi alınamadı: {e}")
        return

    klinik = _select_from_list("🏥 Klinik seç:", klinikler)
    klinik_id = klinik["value"]
    klinik_adi = klinik["text"]

    # Kurum (opsiyonel)
    try:
        kurumlar = requests.get(
            f"https://prd.mhrs.gov.tr/api/kurum/kurum/kurum-klinik/il/{il_id}/ilce/{ilce_id}/kurum/-1/klinik/{klinik_id}/ana-kurum/select-input",
            headers=_headers(token),
            timeout=25,
        ).json().get("data", [])
    except Exception as e:
        print(f"⚠️ Kurum bilgisi alınamadı, Farketmez kabul edilecek: {e}")
        kurumlar = []

    if kurumlar:
        kurumlar_plus = kurumlar + [{"value": -1, "text": "Farketmez"}]
        kurum = _select_from_list("🏛️ Kurum seç:", kurumlar_plus)
    else:
        kurum = {"value": -1, "text": "Farketmez"}

    # Hekim (opsiyonel)
    try:
        if kurum["value"] == -1:
            hekimler = requests.get(
                f"https://prd.mhrs.gov.tr/api/kurum/hekim/hekim-klinik/hekim-select-input/anakurum/-1/kurum/-1/klinik/{klinik_id}",
                headers=_headers(token),
                timeout=25,
            ).json().get("data", [])
        else:
            hekimler = requests.get(
                f"https://prd.mhrs.gov.tr/api/kurum/hekim/hekim-klinik/hekim-select-input/anakurum/{kurum['value']}/kurum/-1/klinik/{klinik_id}",
                headers=_headers(token),
                timeout=25,
            ).json().get("data", [])
    except Exception as e:
        print(f"⚠️ Hekim listesi alınamadı, Farketmez kabul edilecek: {e}")
        hekimler = []

    if hekimler:
        hekimler_plus = hekimler + [{"value": -1, "text": "Farketmez"}]
        hekim = _select_from_list("👨‍⚕️ Hekim seç:", hekimler_plus)
    else:
        hekim = {"value": -1, "text": "Farketmez"}

    # Mod
    while True:
        mod = input("Mod: 1) Otomatik al  2) Sadece bildir  (1/2): ").strip()
        if mod in ("1", "2"):
            break
        print("❌ 1 veya 2 gir.")
    otomatik = (mod == "1")

    # Tarihler
    bugun = datetime.now().strftime("%d.%m.%Y")
    baslangic_tarihi = _input_date("Başlangıç tarihi (gg.aa.yyyy)", default=bugun)
    onbes_gun_sonra = (datetime.now() + timedelta(days=15)).strftime("%d.%m.%Y")
    bitis_tarihi = _input_date("Bitiş tarihi (gg.aa.yyyy)", default=onbes_gun_sonra)

    # Takip nesnesi
    takip = {
        "il_id": il_id,
        "ilce_id": ilce_id,
        "klinik_id": klinik_id,
        "klinik_adi": klinik_adi,
        "kurum_id": kurum.get("value", -1),
        "kurum_adi": kurum.get("text", "Farketmez"),
        "otomatik": otomatik,
        "token": token,
        "hekim_id": hekim.get("value", -1),
        "hekim_adi": hekim.get("text", "Farketmez"),
        "baslangic_tarihi": baslangic_tarihi,
        "bitis_tarihi": bitis_tarihi,
    }

    # 401’de otomatik login istersen (opsiyonel): TC/Şifre’yi takip dict’ine ekleyebilirsin
    if am == "2":
        takip["tc"] = tc
        takip["sifre"] = sifre

    # Kayıt ve çalıştırma
    uid = 1
    aktif_kullanicilar.setdefault(uid, {"aktif": True, "takipler": []})
    aktif_kullanicilar[uid]["takipler"].append(takip)

    print("\n✅ Takip oluşturuldu. Tarama başlıyor (PC modu). Çıkmak için Ctrl+C.\n")
    try:
        # Sonsuz takip döngüsünü gerçekten çalıştır
        asyncio.run(takip_dongusu(uid, "pc_user", takip))
    except KeyboardInterrupt:
        print("\n🛑 Kullanıcı tarafından durduruldu.")

async def async_takip_wrapper(uid, username, takip):
    # asyncio ile uyumlu sarmalayıcı
    await asyncio.to_thread(takip_dongusu_blocking, uid, username, takip)

def takip_dongusu_blocking(uid, username, takip):
    # asyncio olmayan beklemeler için ayrı blocking sarmalayıcı
    # mevcut takip_dongusu coroutine olduğu için aynısını time.sleep ile eşdeğer çalıştırmak istersen
    # yukarıdaki takip_dongusu yerine bu fonksiyonu da tercih edebilirdin.
    # Burada mevcut coroutine sürümünü to_thread ile çağırdık, bu fonksiyon opsiyonel.
    pass  # kullanmıyoruz; referans için bırakıldı.

# ===========================
# Entry Point
# ===========================
if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description="MHRS Takip (PC Modu)")
        # Telegram modu kaldırıldı; sadece pc
        args = parser.parse_args()
        main_pc()
    except Exception as e:
        logging.exception("Fatal error: %s", e)
        print(f"❌ Hata: {e}")
