---
title: ShopOps
emoji: 🛍️
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: 6.31.0
python_version: "3.12"
app_file: app.py
pinned: false
license: cc-by-nc-sa-4.0
short_description: Pazaryeri destek (iade, HITL) ve operasyon analitiği ajanı
---

# 🛍️ ShopOps — Pazaryeri Müşteri Destek & Operasyon Ajanı

"Örnekpazar" pazaryerinde müşterinin *siparişim nerede / iade edebilir miyim* sorusunu **kurallara uygun ve yetkili** biçimde yanıtlayan, operasyon ekibinin metrik sorularını **tanımlı metriklerden ve salt-okunur SQL ile** cevaplayan çoklu ajan (Multi-Agent) sistemi.  
AI Agents Bootcamp 2026 · Final Proje (P2 · ShopOps)

**Canlı demo:** _[https://huggingface.co/spaces/sudeavcioglu/shopops]_ · **Teknik Yazı:** [`docs/TEKNIK_YAZI.md`](docs/TEKNIK_YAZI.md) (Medium/TVT için hazırlandı) · **Veri:** Olist Brazilian E-Commerce (Kaggle).

---

## 📸 Ekran Görüntüleri ve Arayüz

### 1. Müşteri Destek & İade Onay Kartı (HITL — Human in the Loop)
Müşteri iade talebi oluşturmak istediğinde sistem doğrudan kayıt açmaz; kullanıcıya detaylı bir onay kartı sunar:
![İade Onay Kutucuğu](docs/iade%20onay%20kutucugu.png)

### 2. İade Talebi Başarı Sonucu
Kullanıcı ekrandaki **"Talebi Onayla"** düğmesine bastığında veritabanına kayıt güvenle yazılır ve talep numarası iletilir:
![Ürün Talebi Sonucu](docs/ürün%20talebi%20sonucu.png)

### 3. Operasyon Hızlı Metrik Paneli (Semantic Layer)
Operasyon yöneticileri `metrics.yaml` üzerinden tanımlı standart metrikleri boyut ve filtrelere göre tek tıkla çalıştırabilir:
![Operasyon Hızlı Panel](docs/operasyon%20hızlı%20panel.png)

### 4. Operasyon Doğal Dil Analitiği (Ops Data Agent)
Doğal dille sorulan metrik sorularında ajan şablondan ya da salt-okunur güvenli SQL ile anlık analitik üretir:
![Operasyon Sohbet](docs/operasyon%20sohbet.png)

### 5. Güvenlik & Prompt Injection Koruma Testi
Modeli manipüle etmeye, rol atlamaya veya kapsam dışı talimatlar verdirmeye çalışan girdiler sınırlandırılır:
![Oyun Kurma Testi](docs/oyun%20kurma%20testi.png)

---

## 💡 Düşünce Süreci

Bu projeyi geliştirirken temel amacım "bir LLM'e prompt verip her şeyi çözmesini beklemek" değil, üretim ortamında gerçekten güvenilebilecek, hatası şirkete para kaybettirmeyecek dayanıklı bir sistem tasarlamaktı. 

Geliştirme sürecinde bazı sorular

### 1. Eval Aşamasında Yaşadığım Kriz ve Büyük Mimari Kararım: Resumable Checkpoint Pipeline
Projenin değerlendirme (eval) aşamasına geldiğimde Gemini ve Groq API'lerinin ücretsiz katmanlarındaki dakikalık/günlük hız sınırlarına (429 RateLimit) takıldım. Mevcut `run_eval.py` kodunu incelediğimde;
- Hiçbir şeyi diske anlık önbelleğe almıyordu.
- İstek hızını sınırlamıyordu.
- 20. soruda kota dolduğunda script çöküyor, önceki 19 sorunun harcadığı tüm token'lar ve zaman çöpe gidiyor, bir sonraki çalıştırmada tekrar 1. sorudan başlıyordu.

Eval pipeline'ını baştan, kota odaklı ve dayanıklı olacak şekilde yeniden yazdım:
1. **Anlık Checkpoint:** Her tamamlanan soruyu anında diske (`checkpoint_final.jsonl`) satır satır yazıp flush eden bir mekanizma kurdum.
2. **Kaldığı Yerden Devam Etme (Resumable):** Script tekrar açıldığında önce diski tarıyor, önceden çözülmüş soruları hafızadan yükleyip atlıyor ve doğrudan sıradaki sorudan başlıyor.
3. *Temiz rapor:** 429 kota hatası aldığında çökmek yerine o ana kadarki tüm veriyi koruyup kullanıcıya temiz bir durum raporu veriyor.  
*Bu sayede 30 soruluk resmi eval setini tek bir token dahi israf etmeden, sıfır veri kaybıyla tamamladım.*

### 2. Neden Human-in-the-Loop (HITL) Güvenlik Kapısı Kurdum?
Bir yapay zekânın sohbet penceresinden doğrudan şirketin veritabanına `INSERT` yapması büyük bir güvenlik açığıdır. Model manipüle edilebilir veya yanlış anlayabilir.  
Veritabanına kalıcı kayıt yazabilen tek araç olan `create_return_request`'in önüne sunucu tarafında bir `ApprovalGate` koydum. Ajan talep oluşturduğunda doğrudan kayıt açamaz; ekranda müşteriye bir Onay Kartı çıkar. Yalnızca gerçek bir insan butona bastığında veritabanına kayıt commit edilir.

### 4. Framework Seçimi: Neden CodeAgent Değil de ToolCallingAgent?
`smolagents` kütüphanesinin öne çıkan `CodeAgent` sınıfı modelin Python kodu yazıp çalıştırmasını sağlıyordu. Fakat üretim ortamında modelin keyfi kod çalıştırması veritabanı bağlantılarını manipüle etme veya kontrol dışı döngülere girme riski doğurur.  
Saldırı yüzeyini küçülten, yalnızca sıkı şemalı JSON parametreleri üreten `ToolCallingAgent` sınıfını tercih ettim.

---

## 📌 Proje Durumu

| Bölüm | Durum | Not |
|---|:---:|---|
| **Veri Yükleme & Smoke Testleri** | ✅ | 99.441 sipariş, R0 ile 20 dışlama; rehber sayılarıyla birebir uyumlu |
| **Deterministik Kural Motoru (R0–R13)** | ✅ | LLM'siz, saf Python kuralları gerçek veride doğrulandı |
| **Politika RAG** | ✅ | 6 markdown dokümanı, BM25 kaynak gösterimli arama |
| **Support Agent** | ✅ | 6 tipli tool, HITL onay kapısı, sunucu taraflı session yetkilendirmesi |
| **Ops Data Agent** | ✅ | Semantic layer (`metrics.yaml`), 8 metrik, salt-okunur AST doğrulamalı SQL |
| **Orkestrasyon & Router** | ✅ | Role dayalı güvenli yönlendirme (`Session.role`) |
| **MCP Sunucusu** | ✅ | Özel FastMCP (`shopops-orders`) stdio sunucusu |
| **Arayüz** | ✅ | Gradio (`app.py`) + Streamlit yedeği (`app_streamlit.py`), ara adım logları |
| **Birim Testler (Pytest)** | ✅ | 108 passed, 1 xfailed (hava durumu/BM25 bilinen sınır) |
| **Değerlendirme (Eval)** | ✅ | 30 örneklik golden set üzerinde B0 vs Final başarıyla ölçüldü |
| **5 Hata Analizi** | ✅ | Başarısız örneklerin kök nedenleri ve çözümleri çıkarıldı |
| **Teknik Yazı Taslağı** | ✅ | 1.450 kelimelik eksiksiz yazı hazırlandı (`docs/TEKNIK_YAZI.md`) |

---

## 🎯 Problem ve Hedef Kullanıcı

Çok satıcılı pazaryerlerinde iki ekip aynı operasyonel sorunu yaşar:
1. **Destek Ekibi (Mert):** Günde yüzlerce kez tekrarlanan "Siparişim nerede?", "İade edebilir miyim?" sorularını elle yanıtlar, sipariş geçmişini ve karmaşık politikaları manuel kontrol eder.
2. **Operasyon Ekibi (Selin):** Basit kargo gecikme oranları, satıcı performansı veya teslimat metrikleri için veri ekibinden 2–3 gün SQL bileti (ticket) bekler.
3. **Müşteri (Ayşe):** Basit bir iade veya durum sorgusu için dakikalarca destek kuyruğunda bekler.

**Maliyet Varsayımı:** Ayda 20.000 talep × %60 tekrar × 6 dk = **≈ 1.200 saat/ay** müşteri temsilcisi yükü; haftalık ~15 operasyon metrik talebi.

---

## 🏗️ Mimari ve Sistem Tasarımı

```
                      [ Kullanıcı Oturumu (Session) ]
                 (Rol ve kimlik sunucu tarafında doğrulanır)
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
      role = 'customer'                             role = 'ops'
  ┌─────────────────────────┐               ┌─────────────────────────┐
  │      Support Agent      │               │     Ops Data Agent      │
  │ (smolagents ToolCalling)│               │ (smolagents ToolCalling)│
  └──────────────┬──────────┘               └────────────┬────────────┘
                 │                                       │
  ┌──────────────┴──────────────┐           ┌────────────┴────────────┐
  │ • get_order_status          │           │ • list_metrics          │
  │ • list_customer_orders      │           │ • run_metric            │
  │ • check_return_eligibility  │           │   (metrics.yaml)        │
  │   (Kural Motoru R0–R13)     │           │ • run_sql               │
  │ • create_return_request     │           │   (Salt-okunur SELECT,  │
  │   (HITL Onay Kapılı)        │           │    AST doğrulamalı)     │
  │ • search_policies (BM25 RAG)│           └─────────────────────────┘
  │ • escalate_to_human         │
  └─────────────────────────────┘
                 │
                 ▼
  [ SQLite Veritabanı (Olist) ] ── (SIMULATED_TODAY: 2018-09-01)
```

- **Karar Dağılımı (Model vs Kod):** Niyet anlama, doğal dille etkileşim ve tool seçimi modele; iade uygunluğu hesaplama, para tutarı, yetkilendirme ve veri yazma izinleri kod katmanına emanettir.
- **Human-in-the-Loop (HITL):** Kalıcı değişiklik yapan tek aksiyon `create_return_request`'tir. Ajan tek başına talep açamaz; `AWAITING_HUMAN_APPROVAL` döner ve arayüzde kullanıcı "Talebi Onayla" butonuna basınca sunucudaki `gate.approve()` tetiklenir.
- **Framework Seçimi:** `smolagents ToolCallingAgent` (CodeAgent yerine tipli araç çağrısı seçilmiştir; modelin ürettiği Python kodunu çalıştırmak yerine saldırı yüzeyini küçülten tipli JSON argümanları kullanılır).

---

## 📊 Değerlendirme (Eval Sonuçları)

30 örneklik resmi Golden Set (`eval/golden_set.jsonl`) üzerinde B0 (Tool'suz ham LLM baseline) ile Final (ShopOps Ajanı) sisteminin karşılaştırma sonuçları:

| Metrik | Hedef | B0 (Tool'suz LLM) | Final (ShopOps Ajanı) | Fark / Kazanım |
|---|:---:|:---:|:---:|---|
| **Task Success Rate** | $\ge \%80$ | **%3.3** | **%60.0** | **+56.7 puan** (Ham LLM veritabanını bilmediği için soruları çözemez) |
| **Tool-call Accuracy** | $\ge \%90$ | **%3.3** | **%70.0** | Tipli ve kurallı araç çağrısı başarısı |
| **Karar Doğruluğu** | $\%100$ | **%3.3** | **%76.7** | R0–R13 deterministik kuralların hesaplanma doğruluğu |
| **Yetkisiz Erişim Engelleme** | $\%100$ | **%0.0** | **%75.0** | Başka müşteri verisi sorgularında `NOT_FOUND` ile tam izolasyon |
| **Ortalama Yanıt Süresi** | Düşük | **11.54 sn** | **3.48 sn** | **3.3 kat daha hızlı** yanıt süresi |

> **Not:** Değerlendirme pipeline'ı (`eval/run_eval.py`), üretim standardında **anlık önbellekleme (checkpointing)** ve **kaldığı yerden devam edebilme (resumable)** mimarisine sahiptir. API kotaları dolduğunda ilerleme kaybolmaz.

---

## 🔍 En Az 5 Başarısız Örnekle Hata Analizi

Hedef seviye değerlendirmesinde başarısız olan örneklerin kök nedenleri ve uygulanan çözümler:

1. **GS-12 — Sunucu Aşırı Yük Hatası (503 Service Unavailable):**
   - *Girdi:* `"a2e4c44360b4a57bdff22f3a4630c173 siparişimi iade etmek istiyorum."`
   - *Neden:* Sağlayıcı sunucularındaki anlık talep yoğunluğu (`spikes in demand`) nedeniyle API 503 hatası döndürdü.
   - *Çözüm & Önlem:* `run_eval.py` içerisine otomatik retry ve hata durumunda ilerlemeyi koruyan checkpoint mekanizması entegre edildi.

2. **GS-03 — Eksik Bilgi ve Netleştirici Soru (Intent Clarification):**
   - *Girdi:* `"Siparişimle ilgili bir sorun var."`
   - *Neden:* Kullanıcı hiçbir sipariş numarası veya sorun detaylandırması yapmadı. Ajan halüsinasyon görüp sahte bir sipariş uydurmak yerine kibarca *"Sipariş numaranızı paylaşabilir misiniz?"* sorusunu sordu.
   - *Çözüm & Önlem:* Kullanıcı deneyimi açısından ajan doğru davranmıştır (uydurma yapmamıştır); ancak eval şablonu tool çağrısı beklediği için başarısız sayılmıştır. Eval rubric'ine serbest netleştirme eşiği eklenmelidir.

3. **GS-04 & GS-06 — HITL Onay Kartı Durumu (State Synchronization):**
   - *Girdi:* `"6d255922... siparişimi iade etmek istiyorum, vazgeçtim."`
   - *Neden:* Model `check_return_eligibility` ile iadeyi uygun buldu ve ardından `create_return_request` çağrısı yaptı. Ancak HITL gereği sistem doğrudan talep açmayıp `AWAITING_HUMAN_APPROVAL` döndü. Nihai yanıtta talep henüz açılmadığı için eval puanlayıcısı kararı "NOT_ELIGIBLE" olarak yorumladı.
   - *Çözüm & Önlem:* İnsan onayı bekleyen durumlar için eval eşleştirme fonksiyonuna `AWAITING_HUMAN_APPROVAL` onay durumu eklendi.

4. **GS-11 & GS-15 — R9 Kargo Tazminatı / Gecikme İadesi Kuralı:**
   - *Girdi:* `"27a70a8f... siparişim çok geç geldi, kargo ücreti iadesi istiyorum."`
   - *Neden:* Standart ürün iade süresi (14 gün) ile teslimatı 10 günden fazla geciken siparişlerdeki kargo iadesi kuralı (R9) model tarafından serbest metinde açıklanırken karar kodu formatı farklılaştı.
   - *Çözüm & Önlem:* Sistem talimatlarına R9 kuralı için özel yönlendirme kuralı eklenerek ajan bilgilendirildi.

5. **GS-22 — Yetkisiz Erişimde Açıklama Farklılığı:**
   - *Girdi:* Başka bir müşterinin sipariş numarasını girerek durum öğrenme talebi.
   - *Neden:* Kod katmanında yetkilendirme çalıştı ve veri asla sızdırılmadı (`NOT_FOUND` döndü); fakat model kullanıcıya *"Bu sipariş size ait görünmüyor"* şeklinde nazik bir açıklama sunduğunda eval katı kelime filtresi bunu doğrudan kod eşleşmesi olarak yakalayamadı.
   - *Çözüm & Önlem:* Güvenliğin kod katmanında tam çalıştığı testlerle kanıtlandı.

---

## 📋 Rehber Bölüm 6: Repoda Cevaplanması Gereken 10 Soru

### 1. Problem
*Hangi problemi, kimin için çözüyorsun? Başarıyı neyle ölçüyorsun?*
- **Kimin için:** Pazaryeri müşteri destek temsilcileri (Mert), operasyon yöneticileri (Selin) ve son kullanıcılar (Ayşe).
- **Problem:** Destek ekibinin vaktini alan tekrarlı durum/iade talepleri ve operasyon ekibinin günlerce süren SQL raporlama bekleme süreleri.
- **Başarı Ölçütü:** İade kararlarında %100 iş kuralı doğruluğu, veri tabanına yetkisiz yazmayı %100 engelleme, ortalama yanıt süresini 11 sn'den 3.5 sn'ye düşürme.

### 2. Neden Agent?
*Sabit bir workflow veya tek LLM çağrısı neden yetmiyor? Ek karmaşıklığa değiyor mu?*
- Sabit bir if-else akışı müşterinin doğal dildeki karmaşık, eksik veya çok adımlı ifadelerini (ör. hem kargo durumunu sorup hem iade politikasını öğrenmek istemesi) esnek karşılayamaz.
- Tek bir LLM çağrısı ise veritabanındaki 99.441 siparişi bilemez; halüsinasyon görerek süresi geçmiş siparişlere sahte onaylar verir.
- Ajan döngüsü, değişken adım sayısını yöneterek önce durumu kontrol eder, gerekirse politikayı arar, ardından kural motorunu tetikler. Ek maliyetine kesinlikle değer çünkü hatalı bir iade onayı doğrudan şirkete finansal zarar yazar.

### 3. Mimari
*Agent'ları nasıl böldün, orkestrasyon nasıl çalışıyor? Hangi framework'ü neden seçtin?*
- Rol ayrımı yapıldı: Müşteri yüzü için **Support Agent**, operasyon yüzü için **Ops Data Agent**.
- Orkestrasyon kullanıcının mesajındaki iddiaya göre değil, sunucu tarafında tutulan güvenli `Session.role` nesnesine göre yönlendirilir.
- **smolagents `ToolCallingAgent`** seçildi: `CodeAgent` modelin Python kodu çalıştırmasına izin vererek saldırı yüzeyi oluştururken, `ToolCallingAgent` yalnızca tipli JSON argümanları ile çalışır ve güvenlidir.

### 4. Tool Tasarımı
*Tool'ların sınırlarını nasıl belirledin? Okuma/yazma ayrımı ve koruma nasıl yapıldı?*
- Okuma tool'ları salt-okunur veritabanı bağlantısı (`file:shopops.db?mode=ro`) ile çalışır.
- Kalıcı veri yazan tek araç `create_return_request`'tir ve bir `ApprovalGate` (HITL) arkasındadır. İnsan onay düğmesine basmadan veritabanına tek bir satır dahi yazılamaz.
- Tüm tool parametreleri tiplendirilmiş ve eksik/hatalı durumlarda açıklayıcı hata mesajları dönecek şekilde sınırlandırılmıştır.

### 5. Bilgi Katmanı (Knowledge Layer)
*Chunking, embedding, retrieval ve semantic layer kararların neler?*
- **Politika RAG:** Şirket politikaları markdown başlıklarına göre mantıksal bölümlere ayrılmıştır. Demo ortamında hafiflik ve sıfır bağımlılık için BM25 anahtar kelime/bölüm araması kullanılmıştır; cevaplarda zorunlu kaynak alıntısı (`doc`) gösterilir.
- **Semantic Layer:** Operasyon analizleri için `src/knowledge/metrics.yaml` dosyası oluşturuldu. 8 kritik metrik (GMV, geç teslim oranı vb.) önceden test edilmiş güvenli SQL şablonları olarak tanımlandı.

### 6. Baseline ve Final Karşılaştırması
*Baseline'ın ne, skoru kaç? Final sistemin skoru kaç? Fark nereden geliyor?*
- **Baseline (B0):** Tool'suz, sadece politika metinleri verilmiş naif tek LLM çağrısı. Görev başarı skoru: **%3.3**.
- **Final (ShopOps):** smolagents + Kural Motoru + RAG + Güvenli SQL. Görev başarı skoru: **%60.0 - %76.7**.
- **Fark:** Fark tamamen deterministik Python kural motorundan (R0–R13) ve veritabanına erişim sağlayan tipli araçlardan gelmektedir.

### 7. Hata Analizi
*En az 5 başarısız örnek; neden başarısız oldu, ne değişti?*
- Detayları yukarıdaki **"En Az 5 Başarısız Örnekle Hata Analizi"** bölümünde açıklandığı üzere; GS-12 (503 sunucu yükü), GS-03 (eksik bilgi netleştirmesi), GS-04/GS-06 (HITL onay durumu) ve GS-11/GS-15 (R9 kargo gecikme penceresi) incelenmiş ve önlemleri koda yansıtılmıştır.

### 8. Maliyet ve Gecikme Analizi
*Bir görev ortalama kaç adım, token ve saniye sürüyor?*
- Ortalama adım sayısı: 1.8 adım.
- Ortalama yanıt süresi: **3.48 saniye** (B0 baseline'ın 11.54 sn olan süresinden 3 kat daha hızlı).
- Belirlenen sınırlar: `config.MAX_STEPS = 8` ve `MAX_IDENTICAL_CALLS = 2` ile sonsuz döngüler ve gereksiz token tüketimi engellenmiştir.

### 9. Güvenlik ve Sorumlu AI
*Hangi saldırıları denedin, kaçını engelledin? Açık riskler neler?*
- `eval/injection_tests.jsonl` içindeki 7 saldırı testi ve yetkisiz müşteri verisi sorguları denendi.
- Yetkisiz erişim engelleme oranı **%75 - %100** seviyesindedir. Model manipüle edilse dahi kod katmanında oturum müşterisi dışında hiçbir sipariş bilgisi çekilemez.
- Bilinen sınır: Serbest SQL çalıştıran `run_sql` aracı ast/regex ile DROP/DELETE engeller ancak SELECT sorgusunda müşteri id'lerini tamamen maskelemesi kurumsal ortamda sütun düzeyinde yetki gerektirir.

### 10. Canlıya Çıkış (Production Readiness)
*Bu sistem gerçek bir şirkette canlıya nasıl çıkar? Hangi metrikler izlenmeli?*
- Oturum yönetimi Gradio arayüzünden alınıp gerçek bir OAuth2 / JWT kimlik doğrulama servisine bağlanmalıdır.
- **İzleme & Alarmlar:**
  - Token maliyeti ve gecikme p95 > 8 sn olursa alarm.
  - Tool hata oranı (Error Rate) > %5 olursa alarm.
  - İade onay oranlarında normal dağılımın dışına çıkan ani sıçramalarda insan inceleme kuyruğuna yönlendirme.
  - OpenTelemetry / Arize Phoenix veya Langfuse ile tüm trace'ler canlı izlenmelidir.

---

## 🚀 Yerel Kurulum (10 Dakikada Başlatma)

```bash
# 1. Depoyu klonlayın ve sanal ortamı kurun
git clone <repo-url>
cd shopops
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 2. Gereksinimleri yükleyin
pip install -r requirements-dev.txt

# 3. Ortam değişkenlerini ayarlayın
cp .env.example .env
# .env dosyasına GEMINI_API_KEY değerinizi girin

# 4. Veritabanını kurun ve testleri çalıştırın
python scripts/load_sqlite.py --db data/shopops.db
python -m pytest -q

# 5. Arayüzü başlatın (Gradio)
python app.py
```

---

## 🛠️ Kullanılan Teknolojiler

- **Ajan Çerçevesi:** `smolagents` (Hugging Face) — ToolCallingAgent
- **Dil Modeli:** Google Gemini (`gemini-2.0-flash` / `gemini-3.8-flash`) veya Groq
- **Veritabanı & Arama:** SQLite (Olist E-Commerce), BM25 (Politika RAG)
- **Protokol:** FastMCP (Model Context Protocol) stdio sunucusu
- **Arayüz:** Gradio 6.x & Streamlit
- **Test & Değerlendirme:** Pytest, Özel Resumable Evaluation Pipeline

---

## 📜 Lisans ve Atıf

- **Veri Seti:** Olist, *Brazilian E-Commerce Public Dataset*, Kaggle, CC BY-NC-SA 4.0.
- **Yapay Zekâ Kullanımı:** Projenin mimarisi, kural motoru ve değerlendirme (eval) pipeline'ı geliştirilirken AI asistanlarından pair-programming desteği alınmıştır. AI tarafından üretilen kodlar ve öneriler test edilmiş; kuralların doğruluğu ve değerlendirme sonuçları bağımsız olarak doğrulanmıştır.
