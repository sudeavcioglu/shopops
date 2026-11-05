# 📑 Mimari Karar Kayıtları (Architecture Decision Records - ADR)

Bu belge, **ShopOps** projesinin geliştirilmesi sırasında alınan temel mimari ve mühendislik kararlarını, gerekçelerini, alternatiflerini ve sonuçlarını kayıt altına alır.

---

## ADR-001: smolagents Framework ve ToolCallingAgent Seçimi

- **Durum:** Kabul Edildi
- **Tarih:** Ekim 2026
- **Karar:** `smolagents` kütüphanesinin `ToolCallingAgent` sınıfı birincil ajan yürütücüsü olarak seçildi.
- **Alternatifler:** `CodeAgent` (Python kodu yazıp yürüten model) veya LangChain / CrewAI.
- **Neden Seçildi?:** `CodeAgent` modelin çalışma zamanında keyfi Python kodu çalıştırmasını sağlar. Bu durum veritabanı bağlantılarını manipüle etme veya beklenmeyen sistem çağrıları yapma riski doğurur. `ToolCallingAgent` ise yalnızca sıkı tipli JSON şemaları üzerinden araç çağrısı yapar; saldırı yüzeyini minimuma indirir ve yetkilendirmeyi kod katmanında tutar.

---

## ADR-002: Deterministik Python Kural Motoru (R0–R13) vs LLM İnisiyatifi

- **Durum:** Kabul Edildi
- **Tarih:** Ekim 2026
- **Karar:** İade uygunluğu, hak sahipliği pencereleri ve iade tutarları **asla dil modeline hesaplatılmaz**; saf Python ile yazılan deterministik kural motoru tarafından hesaplanır.
- **Alternatifler:** Politika metinlerini modele verip "İadeye uygun mu?" sorusunu doğrudan modele sormak.
- **Neden Seçildi?:** LLM'ler tarih farkı hesaplarında ve sınır günlerde (örneğin 14. günün dolması, 10 günlük kargo gecikmesi) halüsinasyon görebilir. E-ticarette hatalı bir onay doğrudan finansal zarar ve usulsüzlük doğurur. Karar kodda, dilsel açıklama modelde kalmalıdır.

---

## ADR-003: Human-in-the-Loop (HITL) Güvenlik Kapısı

- **Durum:** Kabul Edildi
- **Tarih:** Ekim 2026
- **Karar:** Veritabanına kalıcı kayıt yazabilen `create_return_request` aracı, bir insan onay mekanizması (`ApprovalGate`) arkasına alındı.
- **Alternatifler:** Modelin onay verdiği anda doğrudan veritabanına `INSERT` yapması.
- **Neden Seçildi?:** Dışa etki eden veya kalıcı kayıt değiştiren hiçbir işlem yapay zekânın tek taraflı kararıyla gerçekleşmemelidir (Genel Rehber §8 kuralı). Kullanıcıya arayüzde açık bir Onay Kartı ve butonu sunulur; ancak insan butona bastığında kayıt commit edilir.

---

## ADR-004: Sunucu Taraflı Oturum Yetkilendirmesi (G2 Guardrail)

- **Durum:** Kabul Edildi
- **Tarih:** Ekim 2026
- **Karar:** Müşteri kimliği (`customer_unique_id`) ve oturum rolü (`role`), LLM prompt parametresi olmaktan çıkarılıp sunucu tarafındaki `Session` nesnesinde kilitlendi.
- **Alternatifler:** Model talimatına *"Başka müşterilerin verisini gösterme"* kuralı yazmak.
- **Neden Seçildi?:** Yetkilendirme prompt ile yapılamaz; prompt injection saldırılarıyla model kolaylıkla kandırılabilir. Araçlar sorguladıkları siparişin oturumdaki müşteriye ait olduğunu doğrudan SQL düzeyinde filtreler (`WHERE customer_unique_id = :session_uid`). Başka bir sipariş sorulduğunda model manipüle edilse dahi veri sızdırılamaz, `NOT_FOUND` döner.

---

## ADR-005: Kota Dostu ve Resumable Checkpoint Eval Pipeline

- **Durum:** Kabul Edildi
- **Tarih:** Kasım 2026
- **Karar:** `eval/run_eval.py` script'i her tamamlanan örneği anlık olarak JSONL formatında diske yazan ve 429 kota hatasında kaldığı yeri koruyan bir yapıya kavuşturuldu.
- **Alternatifler:** Tüm test setini hafızada tutup en sonda toplu JSON çıktısı almak.
- **Neden Seçildi?:** Ücretsiz LLM API'lerinin (Gemini, Groq) dakikalık veya günlük hız sınırlarına takıldığında önceki tüm testlerin ve harcanan token'ların kaybolmasını engellemek için endüstri standardı olan "Checkpointing & Resumability" mimarisi uygulandı.

---

## ADR-006: Semantic Layer (`metrics.yaml`) ve Salt-Okunur Güvenli SQL

- **Durum:** Kabul Edildi
- **Tarih:** Ekim 2026
- **Karar:** Operasyon analizleri için 8 standart metrik `metrics.yaml` ile tanımlandı; serbest sorgular için AST denetimli `run_sql` aracı sağlandı.
- **Alternatifler:** Operasyon yöneticisine doğrudan tam yetkili veritabanı konsolu açmak.
- **Neden Seçildi?:** Yanlış metrik tanımları (örneğin GMV'nin net kâr sanılması) operasyonel hatalara yol açar. Semantic layer standart tanımları garanti eder. Serbest sorgular ise `file:shopops.db?mode=ro` bağlantısı ve AST doğrulayıcı ile DDL/DML operasyonlarına karşı korunur.

