"""Olist CSV'lerini SQLite'a yükler.

Yaptıkları:
  * 9 CSV'yi tablolara yükler.
  * R0: order_purchase_timestamp >= SIMULATED_TODAY olan siparişleri (ve bağlı
    kalem/ödeme/yorum satırlarını) DIŞLAR; dışlananlar `_excluded_orders` tablosunda
    tutulur (smoke testi ham sayıları doğrulayabilsin diye).
  * Boş string -> NULL. Zaman damgaları 'YYYY-MM-DD HH:MM:SS' metni olarak kalır.
  * Anahtar kolonlara indeks ekler; boş `return_requests` tablosunu oluşturur. Ham tablolara sonradan yazılmaz.
  * `_load_meta` tablosuna ham/yüklenen satır sayılarını yazar.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import SIMULATED_TODAY  # noqa: E402

CSV_FILES = {
    "customers": "olist_customers_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
    "geolocation": "olist_geolocation_dataset.csv",
}

NUMERIC = {
    "order_items": {"order_item_id": "int", "price": "float", "freight_value": "float"},
    "order_payments": {"payment_sequential": "int", "payment_installments": "int", "payment_value": "float"},
    "order_reviews": {"review_score": "int"},
    "products": {
        "product_name_lenght": "int", "product_description_lenght": "int", "product_photos_qty": "int",
        "product_weight_g": "float", "product_length_cm": "float", "product_height_cm": "float",
        "product_width_cm": "float",
    },
    "geolocation": {"geolocation_lat": "float", "geolocation_lng": "float"},
}

DDL = """
CREATE TABLE customers (
  customer_id TEXT PRIMARY KEY, customer_unique_id TEXT NOT NULL,
  customer_zip_code_prefix TEXT, customer_city TEXT, customer_state TEXT);
CREATE TABLE orders (
  order_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, order_status TEXT NOT NULL,
  order_purchase_timestamp TEXT, order_approved_at TEXT, order_delivered_carrier_date TEXT,
  order_delivered_customer_date TEXT, order_estimated_delivery_date TEXT);
CREATE TABLE order_items (
  order_id TEXT NOT NULL, order_item_id INTEGER NOT NULL, product_id TEXT, seller_id TEXT,
  shipping_limit_date TEXT, price REAL, freight_value REAL, PRIMARY KEY (order_id, order_item_id));
CREATE TABLE order_payments (
  order_id TEXT NOT NULL, payment_sequential INTEGER NOT NULL, payment_type TEXT,
  payment_installments INTEGER, payment_value REAL, PRIMARY KEY (order_id, payment_sequential));
CREATE TABLE order_reviews (  -- review_id ham veride tekil değildir: PK yok
  review_id TEXT, order_id TEXT NOT NULL, review_score INTEGER, review_comment_title TEXT,
  review_comment_message TEXT, review_creation_date TEXT, review_answer_timestamp TEXT);
CREATE TABLE sellers (
  seller_id TEXT PRIMARY KEY, seller_zip_code_prefix TEXT, seller_city TEXT, seller_state TEXT);
CREATE TABLE products (
  product_id TEXT PRIMARY KEY, product_category_name TEXT, product_name_lenght INTEGER,
  product_description_lenght INTEGER, product_photos_qty INTEGER, product_weight_g REAL,
  product_length_cm REAL, product_height_cm REAL, product_width_cm REAL);
CREATE TABLE category_translation (
  product_category_name TEXT PRIMARY KEY, product_category_name_english TEXT);
CREATE TABLE geolocation (
  geolocation_zip_code_prefix TEXT, geolocation_lat REAL, geolocation_lng REAL,
  geolocation_city TEXT, geolocation_state TEXT);
CREATE TABLE return_requests (   -- projenin TEK yazma hedefi (M2'de HITL kapısıyla)
  request_id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id TEXT NOT NULL, customer_unique_id TEXT NOT NULL,
  reason TEXT NOT NULL CHECK (reason IN ('changed_mind','damaged','wrong_item','late')),
  refund_amount REAL NOT NULL, freight_only INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL CHECK (status IN ('PENDING_REVIEW','PENDING_SENIOR','APPROVED','REJECTED')),
  created_at TEXT NOT NULL);
CREATE TABLE _excluded_orders (order_id TEXT PRIMARY KEY, order_status TEXT, order_purchase_timestamp TEXT);
CREATE TABLE _load_meta (table_name TEXT PRIMARY KEY, raw_rows INTEGER, loaded_rows INTEGER);
"""

INDEXES = """
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_status ON orders(order_status);
CREATE INDEX idx_orders_purchase ON orders(order_purchase_timestamp);
CREATE INDEX idx_items_order ON order_items(order_id);
CREATE INDEX idx_items_seller ON order_items(seller_id);
CREATE INDEX idx_items_product ON order_items(product_id);
CREATE INDEX idx_payments_order ON order_payments(order_id);
CREATE INDEX idx_reviews_order ON order_reviews(order_id);
CREATE INDEX idx_customers_unique ON customers(customer_unique_id);
CREATE INDEX idx_customers_state ON customers(customer_state);
CREATE INDEX idx_products_category ON products(product_category_name);
CREATE INDEX idx_returns_order ON return_requests(order_id);
"""


def read_csv(path: Path, table: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df = df.replace({"": None})  # boş string -> NULL
    for col, kind in NUMERIC.get(table, {}).items():
        num = pd.to_numeric(df[col], errors="coerce")
        df[col] = num.astype("Int64") if kind == "int" else num
    return df.astype(object).where(df.notna(), None)


def load(src: Path, db: Path, with_geolocation: bool = False) -> dict:
    if db.exists():
        db.unlink()
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(DDL)
    cutoff = SIMULATED_TODAY.isoformat()  # '2018-09-01' ; metin karşılaştırması güvenli
    report: dict = {"loaded": {}, "skipped": []}
    excluded_ids: set[str] = set()

    # orders önce: R0 dışlama kümesi buradan çıkar
    order = ["orders", "customers", "order_items", "order_payments", "order_reviews",
             "sellers", "products", "category_translation", "geolocation"]
    for table in order:
        path = src / CSV_FILES[table]
        if table == "geolocation" and not with_geolocation:
            report["skipped"].append((table, "Temel'de gerekmez (--with-geolocation)"))
            continue
        if not path.exists():
            report["skipped"].append((table, f"dosya yok: {path.name}"))
            continue
        df = read_csv(path, table)
        raw = len(df)
        if table == "orders":
            mask = df["order_purchase_timestamp"].notna() & (df["order_purchase_timestamp"] >= cutoff)
            exc = df[mask]
            excluded_ids = set(exc["order_id"])
            con.executemany("INSERT INTO _excluded_orders VALUES (?,?,?)",
                            exc[["order_id", "order_status", "order_purchase_timestamp"]].values.tolist())
            df = df[~mask]
        elif table in {"order_items", "order_payments", "order_reviews"} and excluded_ids:
            df = df[~df["order_id"].isin(excluded_ids)]
        cols = list(df.columns)
        con.executemany(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        df.values.tolist())
        con.execute("INSERT INTO _load_meta VALUES (?,?,?)", (table, raw, len(df)))
        report["loaded"][table] = (raw, len(df))
    con.executescript(INDEXES)
    con.commit()
    con.execute("ANALYZE")
    con.close()
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, type=Path, help="Olist CSV klasörü")
    ap.add_argument("--db", default=Path("data/shopops.db"), type=Path)
    ap.add_argument("--with-geolocation", action="store_true")
    a = ap.parse_args()
    rep = load(a.src, a.db, a.with_geolocation)
    for t, (raw, kept) in rep["loaded"].items():
        extra = f"  (R0 ile {raw - kept} satır dışlandı)" if raw != kept else ""
        print(f"{t:<22}{kept:>10,}{extra}")
    for t, why in rep["skipped"]:
        print(f"ATLANDI {t}: {why}")
    print(f"-> {a.db}")


if __name__ == "__main__":
    main()
