import re

from src.knowledge.policies import PolicyIndex, load_chunks, search_policies

def test_every_rule_r0_to_r13_is_covered_by_a_policy():
    covered = {r for c in load_chunks() for r in c.rules}
    assert covered >= {f"R{i}" for i in range(14)}

def test_chunks_have_sources():
    ch = load_chunks()
    assert len(ch) >= 15 and all(c.doc.endswith(".md") and c.section for c in ch)

# sorgu -> beklenen doküman (ilk 3'te)
CASES = [
    ("hasarlı ürün", "hasarli_yanlis_urun.md"),
    ("ürün bozuk geldi iade", "hasarli_yanlis_urun.md"),
    ("kaç gün içinde iade yapabilirim", "iade_politikasi.md"),
    ("siparişimi iptal etmek istiyorum", "iptal_politikasi.md"),
    ("kargo ücretini geri alabilir miyim geç geldi", "gec_teslim_ve_satici_gecikmesi.md"),
    ("voucher ile ödedim iade nasıl olur", "odeme_ve_geri_odeme.md"),
    ("başkasının siparişini görebilir miyim", "siparis_durumu.md"),
    ("sipariş yolda iade", "iptal_politikasi.md"),
    ("500 BRL üzeri iade kim onaylar", "iade_politikasi.md"),
    ("satıcı kargoya geç verdi", "gec_teslim_ve_satici_gecikmesi.md"),
]

def test_top3_contains_right_doc():
    idx = PolicyIndex()
    hit = sum(any(c.doc == doc for c, _ in idx.search(q, 3)) for q, doc in CASES)
    assert hit / len(CASES) >= 0.9, hit

def test_tool_returns_sources():
    r = search_policies("hasarlı ürün")
    assert r["results"][0]["doc"] == "hasarli_yanlis_urun.md" and r["results"][0]["section"]

def test_out_of_policy_question_hands_off():
    r = search_policies("bana python oyunu yaz")  # hiç sözcük örtüşmesi yok
    assert r["results"] == [] and "temsilci" in r["message"]


import pytest

@pytest.mark.xfail(reason="BM25 sınırlaması: 'durum' sözcüğü siparis_durumu ile eşleşir. "
                          "Çözüm: e5 gömme + agent düzeyinde alaka kararı (golden set politika grubunda ölçülecek).")
def test_known_limitation_lexical_false_positive():
    assert search_policies("hava durumu nasıl")["results"] == []

def test_tool_errors():
    assert search_policies("  ")["error"] == "EMPTY_QUERY"
    assert search_policies("iade", k=9)["error"] == "INVALID_K"
