"""app.py yardımcı fonksiyon testleri."""
import pytest
from app import get_demo_customers, get_db_connections


def test_get_db_connections():
    con_ro, con_rw = get_db_connections()
    assert con_ro is not None
    assert con_rw is not None


def test_get_demo_customers():
    demos = get_demo_customers()
    assert len(demos) > 0
    # demo: (uid, order_id, status, deliv_date, price)
    first = demos[0]
    assert len(first[0]) == 32  # customer_unique_id
    assert len(first[1]) == 32  # order_id
    assert first[2] == "delivered"

