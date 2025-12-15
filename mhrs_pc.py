# mhrs_pc.py
import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timedelta
import argparse
import re  # HTML temizlemek için

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
http_logger.propagate = False  # konsola DEBUG/ERROR basmasın, sadece dosyaya yazsın

# ===========================
# Global Durum
# ===========================
# (PC modunda tek kullanıcı senaryosu; yine de yapı korunuyor)
AUTH_METHOD, TOKEN, TC_STATE, SIFRE_STATE, BASLANGIC_TARIHI, BITIS_TARIHI, IL, ILCE, KLINIK, HEKIM, KURUM, OTOMATIK = range(
    12
)
aktif_kullanicilar = {}

# Takip döngüsü bekleme ayarları
WAIT_MIN = 55  # sn
WAIT_MAX = 95  # sn

# Uzun mola ayarları (sabit değil, olasılıklı)
LONG_BREAK_MIN_TRIES = 10         # En az 10 deneme olmadan uzun mola düşünmeyiz
LONG_BREAK_PROB = 0.80           # 10+ denemeden sonra her seferinde %80 ihtimalle uzun mola
LONG_BREAK_SECONDS_MIN = 5 * 60  # 5 dk
LONG_BREAK_SECONDS_MAX = 10 * 60 # 10 dk


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


def _strip_html(s: str) -> str:
    """Basit HTML tag temizleyici (RND4034 mesajındaki font/tagleri atmak için)."""
    if not isinstance(s, str):
        return ""
    # <tag ...>...</tag> basit temizleme
    no_tags = re.sub(r"<.*?>", "", s)
    return no_tags.replace("\r", " ").replace("\n", " ").strip()


# ===========================
# Çekirdek İşlevler
# ===========================
async def randevu_al(slot, token, username, user_id=1):
    """
    Verilen slot için randevu almaya çalışır.
    Başarılıysa hekim/klinik/muayene yeri bilgilerini MHRS cevabından çekip loglar.
    """
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
        http_ok = res.status_code == 200

        # Varsayılanlar (slot’tan gelenler)
        dt = datetime.fromisoformat(slot["baslangicZamani"])
        klinik_adi = slot.get("klinikAdi", "Bilinmiyor")
        hekim_adi = slot.get("hekimAdi", "Bilinmiyor")
        muayene_yeri = slot.get("muayeneYeriAdi") or slot.get("muayeneYeriId", "-")

        # Eğer JSON parse edebilirsek, MHRS cevabından gerçek bilgileri al
        try:
            js = res.json()
        except Exception:
            js = None

        if js:
            data = js.get("data", {}) or {}

            # Hekim adı → "ad" + "soyad"
            hekim_info = data.get("hekim") or {}
            ad = (hekim_info.get("ad") or "").strip()
            soyad = (hekim_info.get("soyad") or "").strip()
            full_name = (ad + " " + soyad).strip()
            if full_name:
                hekim_adi = full_name  # SLOT'tan geleni override et

            # Klinik adı
            klinik_info = data.get("klinik") or {}
            klinik_adi_resp = (klinik_info.get("mhrsKlinikAdi") or klinik_info.get("kisaAdi") or "").strip()
            if klinik_adi_resp:
                klinik_adi = klinik_adi_resp

            # Muayene yeri adı
            muayene_info = data.get("muayeneYeri") or {}
            muayene_yeri_adi = (muayene_info.get("adi") or "").strip()
            if muayene_yeri_adi:
                muayene_yeri = muayene_yeri_adi

        # success flag'i JS'den de kontrol et
        ok = http_ok and ((js or {}).get("success", True))

        if ok:
            user_logger.info(
                (
                    f"{username} - RANDEVU ALINDI | "
                    f"Klinik: {klinik_adi} | "
                    f"Hekim: {hekim_adi} | "
                    f"MuayeneYeri: {muayene_yeri} | "
                    f"Tarih: {dt.strftime('%d.%m.%Y')} | "
                    f"Saat: {dt.strftime('%H:%M')} | "
                    f"SlotId: {slot.get('id')} | "
                    f"CetvelId: {slot.get('fkCetvelId')} | "
                    f"RawBaslangic: {slot['baslangicZamani']}"
                )
            )

            print("\n" + "—" * 40)
            print("✅ Randevu Alındı!")
            print(f"🏥 Klinik: {klinik_adi}")
            print(f"👨‍⚕️ Hekim: {hekim_adi}")
            print(f"📍 Muayene Yeri: {muayene_yeri}")
            print(f"📅 Tarih: {dt.strftime('%d.%m.%Y')}")
            print(f"⏰ Saat:  {dt.strftime('%H:%M')}")
            print("—" * 40 + "\n")
            return True
        else:
            # Teknik detay http_logger'a
            try:
                http_logger.error(
                    "RANDEVU_EKLE HTTP HATA %s - %s",
                    res.status_code,
                    res.text,
                )
            except Exception:
                http_logger.error(
                    "RANDEVU_EKLE HTTP HATA %s - <body okunamadı>",
                    res.status_code,
                )

            user_logger.warning(
                f"{username} - Randevu alma BAŞARISIZ - {res.status_code}"
            )
    except Exception as e:
        user_logger.warning(f"{username} - Randevu alma hatası: {e}")
    return False


async def randevu_sorgula(takip: dict, username="pc_user", user_id=1):
    """
    Uygun slot arar; otomatikse randevu almaya çalışır, değilse bildirir.

    ÖNEMLİ:
      - Hekim seçimi ekranda "Farketmez" olsa bile,
        MHRS API'den gelen her slot hangi hekime aitse
        `hekim_adi` o hekim üzerinden belirlenir.
    """
    token = takip["token"]
    il_id = takip["il_id"]
    ilce_id = takip["ilce_id"]
    klinik_id = takip["klinik_id"]
    klinik_adi = takip["klinik_adi"]
    otomatik = takip["otomatik"]
    hekim_adi_label = takip.get("hekim_adi", "Farketmez")

    # ----- Dinamik tarih aralığı (kayan pencere) -----
    orj_bas = takip.get("baslangic_tarihi")
    orj_bit = takip.get("bitis_tarihi")

    try:
        if orj_bas and orj_bit:
            orj_bas_dt = datetime.strptime(orj_bas, "%d.%m.%Y")
            orj_bit_dt = datetime.strptime(orj_bit, "%d.%m.%Y")
            gun_farki = max(0, (orj_bit_dt - orj_bas_dt).days)
        else:
            # Güvenlik için varsayılan 15 gün
            gun_farki = 15
    except ValueError:
        gun_farki = 15

    # Bugünü baz al, pencereyi kaydır
    bugun = datetime.now()
    baslangic_datetime = bugun.replace(hour=0, minute=0, second=0, microsecond=0)
    bitis_datetime = baslangic_datetime + timedelta(days=gun_farki)

    tarih_araligi_label = (
        f"{baslangic_datetime.strftime('%d.%m.%Y')} - "
        f"{bitis_datetime.strftime('%d.%m.%Y')}"
    )

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

        # 401 → otomatik login (TC/şifre varsa, 5 deneme + 1 saat mola)
        if res.status_code == 401:
            user_logger.warning(f"{username} - Token geçersiz (401).")
            print("⚠️ Token geçersiz (401). Oturum yenilenmeye çalışılacak...")

            # TC/şifre yoksa direkt bırak
            if not (takip.get("tc") and takip.get("sifre")):
                print("❗ Token geçersiz ve TC/Şifre bilgisi yok. Tekrar giriş yapın.")
                return

            max_retry = 5
            yeni_token_alindi = False

            for deneme in range(1, max_retry + 1):
                print(f"🔐 Oturum yenileme denemesi {deneme}/{max_retry}...")
                new_jwt = mhrs_login_get_token(takip["tc"], takip["sifre"])

                if new_jwt:
                    # Başarılı → token güncelle ve aynı isteği yeni token ile tekrar gönder
                    takip["token"] = new_jwt
                    token = new_jwt
                    user_logger.info(f"{username} - Oturum başarıyla yenilendi.")
                    print("✅ Oturum başarıyla yenilendi, randevu sorgusu tekrar deneniyor...")

                    res = requests.post(
                        "https://prd.mhrs.gov.tr/api/kurum-rss/randevu/slot-sorgulama/slot",
                        headers=_headers(new_jwt),
                        json=payload,
                        timeout=25,
                    )
                    yeni_token_alindi = True
                    break
                else:
                    # Bu deneme başarısız → biraz bekle, tekrar dene
                    if deneme < max_retry:
                        wait = random.randint(30, 90)  # 30–90 sn arası bekle
                        print(
                            f"⚠️ Yeniden giriş başarısız. {wait} saniye sonra tekrar denenecek..."
                        )
                        await asyncio.sleep(wait)

            # 5 denemenin hepsi başarısızsa
            if not yeni_token_alindi:
                mola = 3600  # 1 saat
                user_logger.warning(
                    f"{username} - 5 kez oturum yenileme başarısız. {mola//60} dk mola veriliyor."
                )
                print(
                    f"❌ 5 kez yeniden giriş denemesi başarısız. {mola//60} dakika mola veriliyor..."
                )
                await asyncio.sleep(mola)
                return

        # JSON'u bir kere parse edelim
        try:
            js = res.json()
        except Exception:
            js = {}

        if res.status_code != 200:
            # Teknik log
            try:
                http_logger.error(
                    "SLOT HTTP HATA %s - %s",
                    res.status_code,
                    res.text,
                )
            except Exception:
                http_logger.error(
                    "SLOT HTTP HATA %s - <body okunamadı>",
                    res.status_code,
                )

            # Önce warnings'lere bakalım (RND4034 vs burada geliyor)
            warnings_list = js.get("warnings") or []
            if warnings_list and isinstance(warnings_list, list):
                w0 = warnings_list[0] or {}
                kodu = w0.get("kodu", "BILINMIYOR")
                mesaj_html = w0.get("mesaj", "")
                mesaj_plain = _strip_html(mesaj_html)

                # İstediğin formatta tek satır:
                user_logger.info(
                    f"{username} - MHRS UYARI | Kod: {kodu} | Mesaj: {mesaj_plain}"
                )
            else:
                # Eski hata listesi fallback
                hata_kodu = "BILINMIYOR"
                hata_list = js.get("errors") or js.get("errorList") or []
                if hata_list and isinstance(hata_list, list):
                    hata_kodu = hata_list[0].get("kodu", hata_kodu)

                user_logger.error(
                    f"{username} - HTTP HATA {res.status_code} ({hata_kodu}) - Slot sorgusu başarısız."
                )
            return False

        # status_code 200 ise buraya geldik
        data = (js or {}).get("data", [])
        warnings_list = (js or {}).get("warnings") or []

        if not data:
            # Data yok ama warning varsa, yine aynı formatta basalım
            if warnings_list and isinstance(warnings_list, list):
                w0 = warnings_list[0] or {}
                kodu = w0.get("kodu", "BILINMIYOR")
                mesaj_html = w0.get("mesaj", "")
                mesaj_plain = _strip_html(mesaj_html)
                user_logger.info(
                    f"{username} - MHRS UYARI | Kod: {kodu} | Mesaj: {mesaj_plain}"
                )
            else:
                # Sadece klasik "bulunamadı" kaydı
                user_logger.info(
                    f"{username} - RANDEVU BULUNAMADI | Klinik: {klinik_adi} | "
                    f"Hekim: {hekim_adi_label} | Tarih Aralığı: {tarih_araligi_label}"
                )
            return False

        bos_bulundu = False

        # İlk hekim ağaç yapısından boş slot ara
        for hekim in data[0].get("hekimSlotList", []):
            # Hekim bilgisi
            hekim_info = hekim.get("hekim") or hekim

            ad = (hekim_info.get("ad") or "").strip()
            soyad = (hekim_info.get("soyad") or "").strip()
            full_name = (ad + " " + soyad).strip()

            # Eski ihtimalleri de fallback olarak tutalım
            hekim_adi = (
                full_name
                or hekim_info.get("hekimAdi")
                or hekim_info.get("hekimAd")
                or hekim_info.get("hekimAdiSoyadi")
                or hekim_info.get("text")
                or "Bilinmiyor"
            )

            for muayene in hekim.get("muayeneYeriSlotList", []):
                for saat in muayene.get("saatSlotList", []):
                    for sl in saat.get("slotList", []):
                        if sl.get("bos"):
                            bos_bulundu = True

                            enriched = sl["slot"]
                            enriched.update(
                                {
                                    "id": sl["id"],
                                    "baslangicZamani": sl["baslangicZamani"],
                                    "bitisZamani": sl["bitisZamani"],
                                    "fkCetvelId": enriched.get("fkCetvelId"),
                                    "muayeneYeriId": enriched.get("muayeneYeriId"),
                                    "klinikAdi": klinik_adi,
                                    "hekimAdi": hekim_adi,  # SLOT'A AD + SOYAD YAZ
                                }
                            )

                            # Geçmiş slotları ele
                            randevu_zamani = datetime.fromisoformat(
                                enriched["baslangicZamani"]
                            )
                            if randevu_zamani <= datetime.now():
                                continue

                            if otomatik:
                                basarili = await randevu_al(
                                    enriched, token, username, user_id
                                )
                                return basarili
                            else:
                                dt = randevu_zamani
                                hekim_adi_local = enriched.get("hekimAdi", hekim_adi)

                                user_logger.info(
                                    f"{username} - UYGUN RANDEVU BULUNDU (ALINMADI) | "
                                    f"Klinik: {klinik_adi} | "
                                    f"Hekim: {hekim_adi_local} | "
                                    f"Tarih: {dt.strftime('%d.%m.%Y')} | "
                                    f"Saat: {dt.strftime('%H:%M')}"
                                )

                                print("\n" + "—" * 40)
                                print("📢 Uygun Randevu Bulundu!")
                                print(f"🏥 Klinik: {klinik_adi}")
                                print(f"👨‍⚕️ Hekim: {hekim_adi_local}")
                                print(f"📅 Tarih: {dt.strftime('%d.%m.%Y')}")
                                print(f"⏰ Saat:  {dt.strftime('%H:%M')}")
                                print("—" * 40 + "\n")
                                return True

        # Buraya kadar geldiysek data vardı ama hiç boş slot çıkmadı
        if not bos_bulundu:
            user_logger.info(
                f"{username} - RANDEVU BULUNAMADI | Klinik: {klinik_adi} | "
                f"Hekim: {hekim_adi_label} | Tarih Aralığı: {tarih_araligi_label}"
            )
            return False

    except Exception as e:
        user_logger.warning(f"{username} - Randevu sorgulama hatası: {e}")


async def takip_dongusu(user_id, username, takip: dict):
    """
    Takip döngüsü:
      - Her deneme arasında 55–95 sn rastgele bekler.
      - Uzun mola sabit aralıkla değil:
          * En az LONG_BREAK_MIN_TRIES deneme geçmeden uzun mola yok.
          * LONG_BREAK_MIN_TRIES+ denemelerde her seferinde LONG_BREAK_PROB ihtimalle
            LONG_BREAK_SECONDS_MIN–LONG_BREAK_SECONDS_MAX arası uzun mola.
      - Böylece hem insan gibi davranır, hem de MHRS'yi spamlamaz.
    """
    deneme = 0
    since_long_break = 0  # Son uzun moladan bu yana kaç deneme geçti

    while True:
        # Takip iptal edildiyse çık
        if user_id not in aktif_kullanicilar:
            break
        if takip not in aktif_kullanicilar[user_id]["takipler"]:
            break

        # Slot ara
        sonuc = await randevu_sorgula(takip, username, user_id)
        if sonuc:
            # Randevu bulundu → takipten çıkar ve bitir
            try:
                aktif_kullanicilar[user_id]["takipler"].remove(takip)
            except ValueError:
                pass
            user_logger.info(
                f"{username} - Randevu sonrası takip sonlandırıldı: {takip['klinik_adi']}"
            )
            break

        # Buraya geldiysek randevu yok
        deneme += 1
        since_long_break += 1

        # === Uzun mola mı yoksa normal mi? ===
        uzun_mola_yap = False

        # En az LONG_BREAK_MIN_TRIES deneme geçmiş olmalı
        if since_long_break >= LONG_BREAK_MIN_TRIES:
            # Bu denemede belli bir olasılıkla uzun mola
            if random.random() < LONG_BREAK_PROB:
                uzun_mola_yap = True

        if uzun_mola_yap:
            # Uzun mola süresi random
            uzun_bekleme = random.randint(
                LONG_BREAK_SECONDS_MIN,
                LONG_BREAK_SECONDS_MAX,
            )
            dakika = uzun_bekleme // 60
            saniye = uzun_bekleme % 60

            user_logger.info(
                f"{username} - {deneme}. deneme sonrası uzun mola: {dakika} dk {saniye} sn "
                f"(since_long_break={since_long_break})"
            )
            print(
                f"😴 {deneme}. deneme sonrası uzun mola: {dakika} dk {saniye} sn "
                f"(son uzun moladan beri {since_long_break} deneme geçti)"
            )

            # Sayacı sıfırla ve uyu
            since_long_break = 0
            await asyncio.sleep(uzun_bekleme)

            user_logger.info(
                f"{username} - Uzun mola bitti, taramaya devam ediliyor."
            )
            print("⏰ Uzun mola bitti, taramaya devam ediliyor...")

        else:
            # Normal kısa bekleme
            bekleme = random.randint(WAIT_MIN, WAIT_MAX)

            user_logger.info(
                f"{username} - {bekleme} saniye bekleniyor (deneme #{deneme})"
            )
            print(
                f"ℹ️ Randevu bulunamadı. {bekleme} saniye sonra tekrar denenecek... "
                f"(deneme #{deneme})"
            )

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
