# Hugging Face Spaces'e yükleme (Gradio)

Önkoşul (rehbere göre): HF hesabı en az 30 günlük ve e-postası doğrulanmış. Ücretsiz hesap en fazla 2 Gradio ZeroGPU Space açabilir.
Uygulama GPU kullanmaz (LLM bir API'dir); `app.py` içindeki `@spaces.GPU` yer tutucusu yalnızca ZeroGPU'nun başlangıç denetimi içindir.

## 1. Space oluştur
huggingface.co -> profil -> **New Space**
- Space name: `shopops`
- License: `cc-by-nc-sa-4.0`
- SDK: **Gradio**
- Space hardware: **ZeroGPU** (ücretsiz seçenek buysa). ZeroGPU seçilemiyorsa ya da ücret istiyorsa dur ve
  `docs/DEPLOY_STREAMLIT.md` yoluna geç (yedek arayüz: `app_streamlit.py`).
- Visibility: **Public**

## 2. README başlığı
Repo `README.md` dosyasının EN ÜSTÜNE `docs/HF_README_HEADER.md` içindeki `---` ile çevrili bloğu yapıştır
(bloktan önce boş satır ya da başka metin olmamalı).
Build "gradio sürümü bulunamadı" derse `sdk_version` satırını sil.

## 3. Dosyaları yükle
Yüklenecekler: `app.py`, `config.py`, `requirements.txt`, `README.md`, `src/`, `policies/`, `scripts/`
(`scripts/load_sqlite.py` açılışta veritabanını kurmak için gerekli).
Yüklenmeyecekler: `.env`, `data/*.db`, CSV'ler, `traces/`, `eval/golden_set.jsonl`, `tests/` (isteğe bağlı), `.venv/`.

Yol A (web): Space -> Files -> Add file -> Upload files; klasörleri sürükle, **Commit changes to main**.

Yol B (git):
```
git remote add space https://huggingface.co/spaces/<kullanıcı_adı>/shopops
git push space main
```
Kullanıcı adı olarak HF adını, parola olarak **Write yetkili access token** gir
(huggingface.co/settings/tokens). Yeni Space'te hazır bir commit olduğu için push reddedilirse,
yalnızca bu yeni Space için: `git push space main --force`.

## 4. Anahtarı gizli olarak ekle
Space -> **Settings -> Variables and secrets**
- **New secret**: `GEMINI_API_KEY` = anahtarın
- **New variable**: `LLM_PROVIDER` = `gemini`
Secret ekledikten sonra Space kendiliğinden yeniden başlar.

## 5. İzle
**App** sekmesinde build, **Logs**'ta ayrıntı görünür. İlk açılışta uygulama Olist verisini indirip veritabanını kurar
(1-2 dk); sonra "Running" olur. Hata görürsen Logs çıktısını gönder.

## 6. Kontrol listesi
- [ ] "Son siparişlerimi listele" cevap veriyor, "Ara adımlar" dolu
- [ ] İade -> onay kartı -> "Talebi Onayla" -> talep numarası görünüyor
- [ ] Operasyon sekmesi: metrik hesaplanıyor, SQL ve caveat görünüyor
- [ ] Anahtarı geçici olarak yanlış yap: ham hata değil, anlaşılır mesaj çıkıyor
- [ ] README'de canlı link + ekran görüntüsü/GIF + "demo notları"

## Demo notları (README'ye de yaz)
- Space 48 saat trafiksiz kalırsa uyur; uyandığında veritabanı yeniden kurulduğu için ilk açılış yavaştır. Bu normaldir.
- Tüm ziyaretçiler aynı veritabanına yazar: biri bir demo siparişi için talep açarsa diğerleri o sipariş için
  "zaten talep var" görür. "♻️ Demo verisini sıfırla" o oturumda açılanları siler.
- Sekmeler kimlik doğrulamanın yerini tutar (demo); canlıda rol giriş katmanından gelir.
- Keyfi müşteri kimliği girişi yoktur; yalnızca demo müşteriler seçilebilir.
