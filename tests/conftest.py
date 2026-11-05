import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Gerçek veritabanı (data/shopops.db) gerektiren test modülleri: DB yoksa (ör. yeni klon) atlanır.
DB_MODULES = {"test_app_helpers", "test_mcp_server", "test_ops_agent", "test_ops_tools", "test_orchestrator"}


def pytest_collection_modifyitems(config, items):
    import config as app_config   # proje config.py (SHOPOPS_DB / data/shopops.db)
    if app_config.DB_PATH.exists():
        return
    skip = pytest.mark.skip(reason="data/shopops.db yok (python scripts/load_sqlite.py ile kur)")
    for item in items:
        if item.module.__name__.split(".")[-1] in DB_MODULES:
            item.add_marker(skip)
