"""Olist veri setini indirir (kagglehub, hesapsız). Ham veri repoya girmez.

Kullanım:  python data/download.py
Çıktı: CSV'lerin bulunduğu klasör yolu -> scripts/load_sqlite.py --src <yol>
Lisans: CC BY-NC-SA 4.0 (ticari olmayan kullanım, atıf zorunlu).
"""
import kagglehub

if __name__ == "__main__":
    print(kagglehub.dataset_download("olistbr/brazilian-ecommerce"))
