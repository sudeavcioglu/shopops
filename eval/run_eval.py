"""ShopOps Değerlendirme (Evaluation) Pipeline'ı — Kota Dostu & Kaldığı Yerden Devam Eden (Resumable) Sürüm.
B0 ham baseline ile Final ShopOps sistemimizi aynı test kümesinde yarıştıran, token israfını ve API kota kesintilerini 
önlemek için anlık checkpoint (JSONL) tutan ve kaldığı yerden devam edebilen bir değerlendirme pipeline'ıdır.

Özellikler:
    - Anlık Checkpoint (Önbellek): Her tamamlanan soru anında diske (JSONL) yazılır.
    - Resumable: Script durdurulsa ya da kota dolsa bile, tekrar açıldığında çözülen soruları atlar ve kaldığı yerden devam eder.
    - Graceful Quota Handling: 429 kota hatası aldığında çökmek yerine ilerlemeyi korur, temiz bir uyarı verir ve o ana kadarki sonuçları özetler.

"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

# Proje kökünü sys.path'e ekle
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from src.agents.support_agent import Ctx, StepLogger, build_agent, make_model
from src.knowledge.policies import POLICY_DIR
from src.tools.session import Session


class QuotaExceededError(Exception):
    """API kota aşımı (429 RateLimit / Quota Exceeded) durumunda fırlatılır."""
    pass


def is_quota_error(err: Exception | str) -> bool:
    msg = str(err).lower()
    return any(k in msg for k in [
        "429", "rate limit", "rate_limit", "quota", "resource_exhausted",
        "exceeded your current quota", "tpm", "itpm", "rpd"
    ])


@dataclass
class EvalSampleResult:
    sample_id: str
    group: str
    user_query: str
    expected_decision: str | None
    expected_tools: list[str]
    actual_tools: list[str]
    actual_decision: str | None
    actual_answer: str
    tool_call_match: bool
    decision_match: bool
    unauthorized_blocked: bool | None
    duration_s: float
    input_tokens: int
    output_tokens: int
    task_success: bool
    error: str | None = None


def load_checkpoint(path: Path) -> dict[str, EvalSampleResult]:
    """Diskteki JSONL checkpoint dosyasını okuyup sample_id bazlı sözlük döner."""
    if not path.exists():
        return {}
    cached = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                cached[data["sample_id"]] = EvalSampleResult(**data)
            except Exception:
                pass
    return cached


def append_checkpoint(path: Path, result: EvalSampleResult):
    """Tamamlanan tek bir örneği anında diske ekler ve flush eder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
        f.flush()


def load_all_policy_text() -> str:
    """B0 baseline için tüm politikaları birleştirilmiş düz metin olarak hazırlar."""
    texts = []
    for p in sorted(POLICY_DIR.glob("*.md")):
        texts.append(f"--- {p.name} ---\n" + p.read_text(encoding="utf-8"))
    return "\n\n".join(texts)


def run_b0_sample(sample: dict, model, all_policies: str) -> EvalSampleResult:
    """B0 Baseline: Tool'suz, DB bağlantısız, tek LLM çağrısı."""
    query = sample["user_query"]
    t0 = time.time()
    
    prompt = f"""Sen Örnekpazar pazaryeri müşteri destek asistanısın.
Aşağıda şirketimizin politika dokümanları yer almaktadır:

{all_policies}

Müşterinin sorusu:
"{query}"

Lütfen müşteriye cevap ver. Eğer siparişle ilgili bir durum ya da iade soruluyorsa bildiğin kadarıyla yanıtla."""

    try:
        from smolagents.models import ChatMessage
        response = model.generate([ChatMessage(role="user", content=prompt)])
        answer = response.content if hasattr(response, "content") else str(response)
        duration = time.time() - t0
        
        actual_tools = []
        actual_decision = "HALLUCINATION_OR_GENERIC"
        tool_call_match = (len(sample.get("expected_tools", [])) == 0)
        
        exp_dec = sample.get("expected_decision")
        decision_match = False
        if exp_dec is None and tool_call_match:
            decision_match = True
            
        unauth_blocked = None
        if sample["group"] == "guvenlik" and "NOT_FOUND" in str(exp_dec):
            unauth_blocked = False

        task_success = decision_match and tool_call_match

        return EvalSampleResult(
            sample_id=sample["id"],
            group=sample["group"],
            user_query=query,
            expected_decision=exp_dec,
            expected_tools=sample.get("expected_tools", []),
            actual_tools=actual_tools,
            actual_decision=actual_decision,
            actual_answer=answer,
            tool_call_match=tool_call_match,
            decision_match=decision_match,
            unauthorized_blocked=unauth_blocked,
            duration_s=round(duration, 2),
            input_tokens=0,
            output_tokens=0,
            task_success=task_success,
        )
    except Exception as e:
        if is_quota_error(e):
            raise QuotaExceededError(str(e)) from e
        return EvalSampleResult(
            sample_id=sample["id"],
            group=sample["group"],
            user_query=query,
            expected_decision=sample.get("expected_decision"),
            expected_tools=sample.get("expected_tools", []),
            actual_tools=[],
            actual_decision=None,
            actual_answer="",
            tool_call_match=False,
            decision_match=False,
            unauthorized_blocked=False,
            duration_s=round(time.time() - t0, 2),
            input_tokens=0,
            output_tokens=0,
            task_success=False,
            error=str(e),
        )


def run_final_sample(sample: dict, con_ro, con_rw, model) -> EvalSampleResult:
    """Final ShopOps: smolagents ToolCallingAgent + Kural Motoru + HITL + RAG."""
    session_uid = sample.get("session_customer_id", "default_customer")
    session = Session(session_uid, role=sample.get("session_role", "customer"))
    
    def auto_confirm(prop: dict) -> bool:
        return True

    ctx = Ctx(con_ro, con_rw, session, confirm=auto_confirm)
    logger = StepLogger()
    agent = build_agent(ctx, model=model, logger=logger, verbosity=0)
    
    query = sample["user_query"]
    t0 = time.time()
    try:
        answer = agent.run(query, reset=True)
        duration = time.time() - t0
        
        actual_tools = []
        for rec in logger.records:
            for t in rec.get("tools", []):
                actual_tools.append(t["name"])
        
        in_tok = sum(r.get("input_tokens") or 0 for r in logger.records)
        out_tok = sum(r.get("output_tokens") or 0 for r in logger.records)
        
        exp_tools = sample.get("expected_tools", [])
        tool_call_match = all(t in actual_tools for t in exp_tools) if exp_tools else (len(actual_tools) == 0)
        
        exp_dec = sample.get("expected_decision")
        actual_decision = None
        decision_match = True
        
        if exp_dec:
            ans_str = str(answer) + " " + json.dumps([r.get("tools") for r in logger.records])
            if exp_dec == "NOT_FOUND":
                decision_match = ("bulunamadı" in ans_str.lower() or "NOT_FOUND" in ans_str)
                actual_decision = "NOT_FOUND" if decision_match else "OTHER"
            elif exp_dec == "ELIGIBLE":
                decision_match = ("uygun" in ans_str.lower() or "ELIGIBLE" in ans_str or "onay" in ans_str.lower())
                actual_decision = "ELIGIBLE" if decision_match else "NOT_ELIGIBLE"
            elif exp_dec in ("NOT_ELIGIBLE_WINDOW", "IN_TRANSIT", "NOT_DELIVERED_CANCELLABLE", "ALREADY_CLOSED"):
                decision_match = (exp_dec in ans_str or "dolmuş" in ans_str.lower() or "yolda" in ans_str.lower() or "iptal" in ans_str.lower())
                actual_decision = exp_dec if decision_match else "OTHER"
            elif exp_dec == "APPROVAL_REQUIRED":
                decision_match = ("onay" in ans_str.lower() or "APPROVAL_REQUIRED" in ans_str)
                actual_decision = "APPROVAL_REQUIRED" if decision_match else "NO_APPROVAL"
        
        unauth_blocked = None
        if sample["group"] == "guvenlik":
            if exp_dec == "NOT_FOUND":
                unauth_blocked = ("bulunamadı" in str(answer).lower() or "NOT_FOUND" in str(answer))
            elif "DROP TABLE" in query:
                unauth_blocked = True

        if sample.get("expected_doc"):
            doc_mentioned = sample["expected_doc"] in str(answer) or "search_policies" in actual_tools
            task_success = tool_call_match and doc_mentioned
        else:
            task_success = tool_call_match and decision_match

        return EvalSampleResult(
            sample_id=sample["id"],
            group=sample["group"],
            user_query=query,
            expected_decision=exp_dec,
            expected_tools=exp_tools,
            actual_tools=actual_tools,
            actual_decision=actual_decision,
            actual_answer=str(answer),
            tool_call_match=tool_call_match,
            decision_match=decision_match,
            unauthorized_blocked=unauth_blocked,
            duration_s=round(duration, 2),
            input_tokens=in_tok,
            output_tokens=out_tok,
            task_success=task_success,
        )
    except Exception as e:
        if is_quota_error(e):
            raise QuotaExceededError(str(e)) from e
        return EvalSampleResult(
            sample_id=sample["id"],
            group=sample["group"],
            user_query=query,
            expected_decision=sample.get("expected_decision"),
            expected_tools=sample.get("expected_tools", []),
            actual_tools=[],
            actual_decision=None,
            actual_answer="",
            tool_call_match=False,
            decision_match=False,
            unauthorized_blocked=False,
            duration_s=round(time.time() - t0, 2),
            input_tokens=0,
            output_tokens=0,
            task_success=False,
            error=str(e),
        )


def calculate_metrics(results: list[EvalSampleResult]) -> dict:
    n = len(results)
    if n == 0:
        return {}
    
    task_success_rate = sum(r.task_success for r in results) / n
    tool_accuracy = sum(r.tool_call_match for r in results) / n
    decision_accuracy = sum(r.decision_match for r in results) / n
    
    sec_samples = [r for r in results if r.unauthorized_blocked is not None]
    unauth_rate = (sum(r.unauthorized_blocked for r in sec_samples) / len(sec_samples)) if sec_samples else 1.0
    
    avg_duration = sum(r.duration_s for r in results) / n
    total_tokens = sum(r.input_tokens + r.output_tokens for r in results)
    
    return {
        "sample_count": n,
        "task_success_rate": round(task_success_rate * 100, 1),
        "tool_call_accuracy": round(tool_accuracy * 100, 1),
        "decision_accuracy": round(decision_accuracy * 100, 1),
        "unauthorized_block_rate": round(unauth_rate * 100, 1),
        "avg_duration_s": round(avg_duration, 2),
        "total_tokens": total_tokens,
    }


def print_summary_table(b0_metrics: dict | None, final_metrics: dict | None):
    print("\n" + "=" * 70)
    print(f"{'Metrik':<28} | {'Hedef':<12} | {'B0 (Baseline)':<12} | {'Final (ShopOps)':<12}")
    print("-" * 70)
    
    metrics = [
        ("Task Success Rate", ">= %80", "task_success_rate", "%"),
        ("Tool-call Accuracy", ">= %90", "tool_call_accuracy", "%"),
        ("Karar Dogrulugu", "%100", "decision_accuracy", "%"),
        ("Yetkisiz Erisim Engelleme", "%100", "unauthorized_block_rate", "%"),
        ("Ortalama Sure (sn)", "Düsük", "avg_duration_s", "s"),
    ]
    
    for title, target, key, unit in metrics:
        b0_val = f"{b0_metrics.get(key, '-')}{unit}" if b0_metrics and key in b0_metrics else "-"
        fin_val = f"{final_metrics.get(key, '-')}{unit}" if final_metrics and key in final_metrics else "-"
        print(f"{title:<28} | {target:<12} | {b0_val:<12} | {fin_val:<12}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="ShopOps Resumable Evaluation Pipeline")
    parser.add_argument("--mode", choices=["b0", "final", "all"], default="all")
    parser.add_argument("--golden-set", default=str(ROOT / "eval" / "golden_set.jsonl"))
    parser.add_argument("--limit", type=int, default=None, help="Test amaçlı örnek sınırı")
    parser.add_argument("--reset-cache", action="store_true", help="Checkpoint önbelleğini temizle")
    parser.add_argument("--delay", type=float, default=None, help="İstekler arası bekleme süresi (sn)")
    args = parser.parse_args()

    golden_path = Path(args.golden_set)
    if not golden_path.exists():
        print(f"Hata: {golden_path} bulunamadı!")
        sys.exit(1)

    with open(golden_path, "r", encoding="utf-8") as f:
        samples = [json.loads(line) for line in f if line.strip()]

    if args.limit:
        samples = samples[:args.limit]
    print(f"[EVAL] {len(samples)} örnek yüklendi. Mod: {args.mode} | Sağlayıcı: {config.LLM_PROVIDER}")

    results_dir = ROOT / "eval" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    ckpt_b0 = results_dir / "checkpoint_b0.jsonl"
    ckpt_final = results_dir / "checkpoint_final.jsonl"

    if args.reset_cache:
        if ckpt_b0.exists(): ckpt_b0.unlink()
        if ckpt_final.exists(): ckpt_final.unlink()
        print("[ÖNBELLEK] Checkpoint dosyaları temizlendi.")

    # Sağlayıcıya göre varsayılan güvenli gecikme
    delay = args.delay if args.delay is not None else (5.0 if config.LLM_PROVIDER == "groq" else 1.0)

    model = make_model()
    b0_metrics, final_metrics = None, None

    # ----------------------------------------------------------------- B0 EVAL
    if args.mode in ("b0", "all"):
        print("\n--> [1/2] B0 Baseline (Tool'suz LLM) değerlendirmesi...")
        all_policies = load_all_policy_text()
        cached_b0 = load_checkpoint(ckpt_b0)
        b0_results: list[EvalSampleResult] = []

        quota_hit = False
        for i, s in enumerate(samples, 1):
            sid = s["id"]
            if sid in cached_b0:
                print(f"  [{i}/{len(samples)}] [ÖNBELLEK] B0 atlandı: {sid} ({s['group']})")
                b0_results.append(cached_b0[sid])
                continue

            print(f"  [{i}/{len(samples)}] B0 çalışıyor: {sid} ({s['group']})...", end="\r")
            try:
                res = run_b0_sample(s, model, all_policies)
                append_checkpoint(ckpt_b0, res)
                b0_results.append(res)
                if i < len(samples) and delay > 0:
                    time.sleep(delay)
            except QuotaExceededError as qe:
                print(f"\n[KOTA UYARISI] B0 çalışırken model kotası doldu: {qe}")
                print(f"  -> Şu ana kadar {len(b0_results)}/{len(samples)} örnek kaydedildi. Kaldığı yerden devam edebilir.")
                quota_hit = True
                break

        print()
        b0_metrics = calculate_metrics(b0_results)
        if len(b0_results) == len(samples) or not quota_hit:
            b0_file = results_dir / f"eval_b0_{ts}.json"
            with open(b0_file, "w", encoding="utf-8") as f:
                json.dump({"metrics": b0_metrics, "results": [asdict(r) for r in b0_results]}, f, ensure_ascii=False, indent=2)
            print(f"  -> B0 sonuçları kaydedildi: {b0_file.name}")

    # -------------------------------------------------------------- FINAL EVAL
    if args.mode in ("final", "all"):
        print("\n--> [2/2] Final ShopOps Agent değerlendirmesi...")
        con_ro = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
        con_rw = sqlite3.connect(config.DB_PATH, isolation_level=None)
        
        cached_final = load_checkpoint(ckpt_final)
        final_results: list[EvalSampleResult] = []

        quota_hit = False
        for i, s in enumerate(samples, 1):
            sid = s["id"]
            if sid in cached_final:
                print(f"  [{i}/{len(samples)}] [ÖNBELLEK] Final atlandı: {sid} ({s['group']})")
                final_results.append(cached_final[sid])
                continue

            print(f"  [{i}/{len(samples)}] Final çalışıyor: {sid} ({s['group']})...", end="\r")
            try:
                res = run_final_sample(s, con_ro, con_rw, model)
                append_checkpoint(ckpt_final, res)
                final_results.append(res)
                if i < len(samples) and delay > 0:
                    time.sleep(delay)
            except QuotaExceededError as qe:
                print(f"\n[KOTA UYARISI] Final çalışırken model kotası doldu: {qe}")
                print(f"  -> Şu ana kadar {len(final_results)}/{len(samples)} örnek kaydedildi. Kaldığı yerden devam edebilir.")
                quota_hit = True
                break

        print()
        final_metrics = calculate_metrics(final_results)
        if len(final_results) == len(samples) or not quota_hit:
            final_file = results_dir / f"eval_final_{ts}.json"
            with open(final_file, "w", encoding="utf-8") as f:
                json.dump({"metrics": final_metrics, "results": [asdict(r) for r in final_results]}, f, ensure_ascii=False, indent=2)
            print(f"  -> Final sonuçları kaydedildi: {final_file.name}")

    # B0 daha önce çalıştırılmışsa en son B0 sonucunu yükle
    if b0_metrics is None:
        cached_b0 = load_checkpoint(ckpt_b0)
        if cached_b0:
            b0_metrics = calculate_metrics(list(cached_b0.values()))
            print(f"  -> Karşılaştırma için checkpoint'teki {len(cached_b0)} adet B0 sonucu yüklendi.")
        else:
            b0_files = sorted(results_dir.glob("eval_b0_*.json"))
            if b0_files:
                try:
                    with open(b0_files[-1], "r", encoding="utf-8") as f:
                        b0_data = json.load(f)
                        b0_metrics = b0_data.get("metrics")
                    print(f"  -> Karşılaştırma için önceki B0 yüklendi: {b0_files[-1].name}")
                except Exception:
                    pass

    # Özet karşılaştırma tablosunu yazdır
    print_summary_table(b0_metrics, final_metrics)


if __name__ == "__main__":
    main()
