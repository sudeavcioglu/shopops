"""Ops Data Agent tool'ları ve SQL Semantic Layer motoru.

İçerik:
  * list_metrics: Tanımlı metrikleri ve boyutları listeler
  * run_metric: metrics.yaml şablonundan SQL üretir, çalıştırır ve caveat döndürür
  * run_sql: Serbest SQL sorgularını güvenli (salt-okunur + validate_sql) çalıştırır
  * validate_sql: G3 guardrail — DROP/ATTACH/PRAGMA/çoklu komutları kesinlikle engeller
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

import yaml

import config
from src.tools.session import Session

METRICS_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "metrics.yaml"

# G3: Yasaklı SQL sözcükleri (küçük harf kontrolü)
FORBIDDEN_KEYWORDS = {
    "drop", "delete", "update", "insert", "alter", "create", "attach",
    "detach", "pragma", "vacuum", "reindex", "replace", "grant", "revoke"
}


def load_metrics_def() -> dict[str, Any]:
    with open(METRICS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_sql(sql: str) -> tuple[bool, str | None]:
    """G3 Guardrail: Yalnızca tek bir SELECT veya WITH sorgusuna izin verir."""
    cleaned = re.sub(r"--.*?$|/\*.*?\*/", "", sql, flags=re.MULTILINE).strip()
    if not cleaned:
        return False, "Sorgu boş olamaz."

    # Çoklu ifade kontrolü (tırnak içi olmayan noktalı virgül)
    statements = [s.strip() for s in cleaned.split(";") if s.strip()]
    if len(statements) > 1:
        return False, "Güvenlik kuralı: Çoklu SQL komutları çalıştırılamaz."

    # Yalnızca SELECT veya WITH ile başlamalı
    lower_sql = cleaned.lower()
    if not (lower_sql.startswith("select") or lower_sql.startswith("with")):
        return False, "Güvenlik kuralı: Yalnızca SELECT veya WITH (okuma) sorgularına izin verilir."

    # Kelime sınırlarında yasaklı kelimeleri ara
    words = set(re.findall(r"\b[a-zA-Z_]+\b", lower_sql))
    found_forbidden = words.intersection(FORBIDDEN_KEYWORDS)
    if found_forbidden:
        return False, f"Güvenlik kuralı ihlali: '{', '.join(sorted(found_forbidden))}' komutuna izin verilmez."

    return True, None


def _ops_only(session: Session) -> dict | None:
    if session.role != "ops":
        return {"error": "FORBIDDEN", "message": "Bu araç yalnızca operasyon (ops) oturumlarında kullanılabilir."}
    return None


def list_metrics(session: Session) -> dict:
    """Tanımlı operasyon metriklerini, açıklamalarını ve boyutlarını listeler."""
    if (err := _ops_only(session)):
        return err

    m_defs = load_metrics_def()
    out = []
    for k, v in m_defs.items():
        out.append({
            "metric_name": k,
            "title": v.get("title", k),
            "description": v.get("description", ""),
            "grain": v.get("grain", ""),
            "available_dimensions": list(v.get("dimensions", {}).keys()),
            "caveat": v.get("caveat", "")
        })
    return {"metrics": out}


def build_metric_sql(metric_name: str, dimensions: list[str] | None = None,
                     filters: dict[str, str] | None = None, limit: int = 100) -> tuple[str, str]:
    """metrics.yaml tanımından SQL oluşturur ve metriğin caveat metnini döner."""
    m_defs = load_metrics_def()
    if metric_name not in m_defs:
        raise ValueError(f"Tanımsız metrik: {metric_name}. list_metrics ile kontrol edin.")

    m = m_defs[metric_name]
    dims = dimensions or []
    dim_defs = m.get("dimensions", {})
    
    select_cols = []
    group_cols = []
    for d in dims:
        if d not in dim_defs:
            raise ValueError(f"'{d}' boyutu {metric_name} için geçerli değil. Geçerli boyutlar: {list(dim_defs.keys())}")
        col_expr = dim_defs[d]
        select_cols.append(f"{col_expr} AS {d}")
        group_cols.append(col_expr)

    # Filtreler: yalnız tanımlı boyutlar ve güvenli değerler (enjeksiyon + sessiz yok sayma kapalı)
    where_parts = [m.get("base_filter", "1=1")]
    for f_name, f_val in (filters or {}).items():
        if f_name not in dim_defs:
            raise ValueError(f"'{f_name}' filtresi {metric_name} için geçerli değil. Geçerli boyutlar: {list(dim_defs.keys())}")
        if not re.fullmatch(r"[A-Za-z0-9_\- ]{1,64}", str(f_val)):
            raise ValueError(f"'{f_name}' filtre değeri geçersiz karakter içeriyor.")
        where_parts.append(f"{dim_defs[f_name]} = '{f_val}'")

    # Metrik ifadesi (oran ya da toplam)
    if "numerator" in m and "denominator" in m:
        num = m["numerator"]
        den = m["denominator"]
        metric_expr = f"ROUND({num} * 1.0 / NULLIF({den}, 0), 4) AS {metric_name}"
    else:
        metric_expr = f"{m['expression']} AS {metric_name}"

    select_clause = ", ".join(select_cols + [metric_expr])

    # Akıllı JOIN: select + base_filter + FİLTRE İFADELERİNDE geçen tabloları ekle
    all_needed_text = select_clause + " " + " ".join(where_parts)

    joins = []
    if "c." in all_needed_text:
        joins.append("customers c ON c.customer_id = o.customer_id")
    if "i." in all_needed_text or "s." in all_needed_text or "p." in all_needed_text or "t." in all_needed_text:
        joins.append("order_items i ON i.order_id = o.order_id")
    if "s." in all_needed_text:
        joins.append("sellers s ON s.seller_id = i.seller_id")
    if "p." in all_needed_text or "t." in all_needed_text:
        joins.append("products p ON p.product_id = i.product_id")
    if "t." in all_needed_text:
        joins.append("category_translation t ON t.product_category_name = p.product_category_name")
    if "r." in all_needed_text:
        joins.append("order_reviews r ON r.order_id = o.order_id")

    from_clause = "FROM orders o"
    for j in joins:
        from_clause += f"\nJOIN {j}"

    where_clause = "WHERE " + " AND ".join(f"({p})" for p in where_parts)
    
    sql = f"SELECT {select_clause}\n{from_clause}\n{where_clause}"
    if group_cols:
        sql += f"\nGROUP BY {', '.join(group_cols)}"
        sql += f"\nORDER BY {metric_name} DESC"
    sql += f"\nLIMIT {min(limit, config.SQL_ROW_LIMIT)}"

    return sql, m.get("caveat", "")


def run_metric(con: sqlite3.Connection, session: Session, metric_name: str,
               dimensions: list[str] | None = None, filters: dict[str, str] | None = None,
               limit: int = 100) -> dict:
    """Tanımlı bir metriği semantic layer'dan hesaplar ve caveat ile birlikte döner."""
    if (err := _ops_only(session)):
        return err

    try:
        sql, caveat = build_metric_sql(metric_name, dimensions, filters, limit)
    except Exception as e:
        return {"error": "INVALID_METRIC_REQUEST", "message": str(e)}

    # :simulated_today parametresi
    today_str = config.SIMULATED_TODAY.isoformat()
    try:
        cur = con.execute(sql.replace(":simulated_today", f"'{today_str}'"))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return {
            "metric": metric_name,
            "sql": sql,
            "row_count": len(rows),
            "data": rows,
            "caveat": caveat,
            "simulated_today": today_str
        }
    except sqlite3.Error as e:
        return {"error": "SQL_ERROR", "sql": sql, "message": str(e)}


def run_sql(con: sqlite3.Connection, session: Session, sql: str,
            limit: int = config.SQL_ROW_LIMIT) -> dict:
    """Serbest SQL sorgusunu güvenlik filtresinden (G3) geçirerek salt-okunur modda çalıştırır."""
    if (err := _ops_only(session)):
        return err

    is_valid, err_msg = validate_sql(sql)
    if not is_valid:
        return {"error": "SQL_SECURITY_VIOLATION", "message": err_msg}

    # Satır sınırı güvencesi (LIMIT yoksa ekle)
    exec_sql = sql.strip()
    if "limit" not in exec_sql.lower():
        exec_sql += f"\nLIMIT {limit}"

    today_str = config.SIMULATED_TODAY.isoformat()
    exec_sql = exec_sql.replace(":simulated_today", f"'{today_str}'")

    try:
        cur = con.execute(exec_sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [dict(zip(cols, r)) for r in cur.fetchall()[:limit]]
        return {
            "sql": exec_sql,
            "row_count": len(rows),
            "data": rows,
            "caveat": "Gözlemsel veridir; nedensellik iddia edilemez. GMV ciro hacmidir, net kâr değildir."
        }
    except sqlite3.Error as e:
        # Hata mesajı dönülür — Ops Agent self-correction için bunu kullanır
        return {"error": "SQL_EXECUTION_ERROR", "message": str(e), "sql": exec_sql}

