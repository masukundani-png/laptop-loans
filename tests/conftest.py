import os, sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import laptops  # noqa: E402


@pytest.fixture(autouse=True)
def tmp_env(tmp_path, monkeypatch):
    """Point the DB and contract output at a temp dir so real data is never touched."""
    monkeypatch.setattr(laptops, "DB", str(tmp_path / "test.db"))
    monkeypatch.setattr(laptops, "OUT", str(tmp_path / "contracts"))
    return tmp_path


@pytest.fixture
def conn():
    c = laptops.db()
    yield c
    c.close()


@pytest.fixture
def seeded(conn):
    """One student and one laptop; returns (conn, student_id, laptop_id)."""
    s = conn.execute("INSERT INTO students(name,student_no,id_number) VALUES('Thandi Nkosi','2024001','9001015800087')").lastrowid
    l = conn.execute("INSERT INTO laptops(asset_tag,model,serial) VALUES('LT-001','Dell Latitude 3420','SN12345')").lastrowid
    conn.commit()
    return conn, s, l
