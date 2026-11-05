# Yayına alma (Streamlit Community Cloud)

Arayüz Streamlit olduğu için Streamlit Community Cloud kullanılır (ücretsiz, public GitHub reposundan çalışır).
Hugging Face Spaces'te Streamlit çalıştırmak Docker gerektirir; rehbere göre bu ücretli plan demektir.

## 1. GitHub reposu (public)
Repoya GİRMEYENLER: `.env`, `data/*.db`, CSV'ler, `traces/`, `eval/golden_set.jsonl` (ham kimlik içerir).
`.gitignore`'a şu satırı ekle:  `eval/golden_set.jsonl`
Kontrol: `git status` çıktısında .env veya .db görünmemeli.

## 2. Uygulamayı oluştur
share.streamlit.io -> New app -> repo / branch: main / Main file path: `app.py` -> Advanced settings:
- Python 3.12
- Secrets:
```
GEMINI_API_KEY = "buraya_anahtar"
LLM_PROVIDER = "gemini"
```
Deploy'a bas. İlk açılışta uygulama Olist verisini indirip veritabanını kendisi kurar (1-2 dk, "İlk açılış" mesajı görünür).

## 3. Kontrol listesi
- [ ] Müşteri sekmesi: "Son siparişlerimi listele" cevap veriyor
- [ ] İade -> onay kartı -> "Talebi Onayla" -> talep numarası görünüyor
- [ ] "Ara adımlar" paneli tool çağrılarını gösteriyor
- [ ] Operasyon sekmesi: SP / Temmuz 2018 geç teslim oranı = 0,0358
- [ ] Anahtarı sildiğinde / kota dolunca kullanıcı dostu mesaj çıkıyor (ham hata yok)
- [ ] README'de canlı link + ekran görüntüsü

## Demo notları
- Tüm ziyaretçiler aynı veritabanına yazar: bir demo siparişi için talep açılırsa diğer ziyaretçiler aynı siparişte
  "zaten talep var" görür. Sol menüdeki "Demo verisini sıfırla" düğmesi o oturumda açılan talepleri siler;
  uygulama yeniden başlayınca veritabanı zaten sıfırdan kurulur.
- Herkese açık demoda keyfi müşteri kimliği girişi kapalıdır; yerelde açmak için `SHOPOPS_ALLOW_CUSTOM_ID=1`.
- Rol seçici kimlik doğrulamanın yerini tutar (demo). README'de bunu açıkça yaz.
