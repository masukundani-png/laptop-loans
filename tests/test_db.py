import argparse, sqlite3
import pytest
import laptops


def tables(c):
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_schema_created(conn):
    assert {"students", "laptops", "assignments"} <= tables(conn)
    idx = {r[1] for r in conn.execute("PRAGMA index_list(assignments)")}
    assert "one_open_per_laptop" in idx


def test_db_is_in_tmp_not_real(tmp_env):
    assert laptops.DB.startswith(str(tmp_env))
    laptops.db().close()
    assert (tmp_env / "test.db").exists()


def test_db_idempotent_and_adds_id_number_column(tmp_env):
    c = sqlite3.connect(laptops.DB)
    c.execute("CREATE TABLE students(id INTEGER PRIMARY KEY, name TEXT NOT NULL, student_no TEXT UNIQUE, grade TEXT, guardian_name TEXT, guardian_email TEXT)")
    c.commit(); c.close()
    c = laptops.db()
    assert "id_number" in [r[1] for r in c.execute("PRAGMA table_info(students)")]
    c.close()
    laptops.db().close()  # second open must not fail


def test_duplicate_student_no_rejected(conn):
    conn.execute("INSERT INTO students(name,student_no) VALUES('A','1')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO students(name,student_no) VALUES('B','1')")


def test_duplicate_asset_tag_rejected(conn):
    conn.execute("INSERT INTO laptops(asset_tag,model,serial) VALUES('T1','m','s1')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO laptops(asset_tag,model,serial) VALUES('T1','m','s2')")


def test_student_name_required(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO students(name,student_no) VALUES(NULL,'9')")


def test_foreign_keys_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO assignments(student_id,laptop_id,issued_on) VALUES(99,99,'2026-01-01')")


def test_one_open_assignment_per_laptop(seeded):
    c, s, l = seeded
    s2 = c.execute("INSERT INTO students(name,student_no) VALUES('Other','2')").lastrowid
    c.execute("INSERT INTO assignments(student_id,laptop_id,issued_on) VALUES(?,?,'2026-01-01')", (s, l))
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO assignments(student_id,laptop_id,issued_on) VALUES(?,?,'2026-01-02')", (s2, l))


def test_return_then_reassign(seeded):
    c, s, l = seeded
    s2 = c.execute("INSERT INTO students(name,student_no) VALUES('Other','2')").lastrowid
    c.execute("INSERT INTO assignments(student_id,laptop_id,issued_on) VALUES(?,?,'2026-01-01')", (s, l))
    c.execute("UPDATE assignments SET returned_on='2026-02-01' WHERE laptop_id=?", (l,))
    c.execute("INSERT INTO assignments(student_id,laptop_id,issued_on) VALUES(?,?,'2026-02-02')", (s2, l))
    open_rows = c.execute("SELECT * FROM assignments WHERE returned_on IS NULL").fetchall()
    assert len(open_rows) == 1 and open_rows[0]["student_id"] == s2
    assert c.execute("SELECT COUNT(*) FROM assignments").fetchone()[0] == 2


def test_two_laptops_can_be_out_simultaneously(seeded):
    c, s, l = seeded
    l2 = c.execute("INSERT INTO laptops(asset_tag,model,serial) VALUES('LT-002','m','s2')").lastrowid
    c.execute("INSERT INTO assignments(student_id,laptop_id,issued_on) VALUES(?,?,'2026-01-01')", (s, l))
    c.execute("INSERT INTO assignments(student_id,laptop_id,issued_on) VALUES(?,?,'2026-01-01')", (s, l2))


# --- CLI command functions ---

def ns(**k):
    return argparse.Namespace(**k)


def test_cmd_add_student_and_laptop(capsys):
    laptops.cmd_add_student(ns(name="Ann", student_no="5", grade="1", guardian="G", guardian_email="g@x.z", id_number="123"))
    laptops.cmd_add_laptop(ns(tag="X1", model="M", serial="S", value=10.5))
    with laptops.db() as c:
        assert c.execute("SELECT id_number FROM students WHERE student_no='5'").fetchone()[0] == "123"
        assert c.execute("SELECT value FROM laptops WHERE asset_tag='X1'").fetchone()[0] == 10.5


def test_cmd_assign_return_cycle(capsys):
    laptops.cmd_add_student(ns(name="Ann", student_no="5", grade=None, guardian=None, guardian_email=None, id_number="123"))
    laptops.cmd_add_student(ns(name="Bob", student_no="6", grade=None, guardian=None, guardian_email=None, id_number="456"))
    laptops.cmd_add_laptop(ns(tag="X1", model="M", serial="S", value=0))
    laptops.cmd_assign(ns(student_no="5", tag="X1", date="2026-03-01"))
    with pytest.raises(SystemExit) as e:
        laptops.cmd_assign(ns(student_no="6", tag="X1", date="2026-03-02"))
    assert "already assigned" in str(e.value)
    capsys.readouterr()
    laptops.cmd_return(ns(tag="X1", date="2026-04-01"))
    assert capsys.readouterr().out.strip() == "Returned"
    laptops.cmd_return(ns(tag="X1", date=None))
    assert "not currently assigned" in capsys.readouterr().out
    laptops.cmd_assign(ns(student_no="6", tag="X1", date="2026-04-02"))
    laptops.cmd_signed(ns(id=2, date="2026-04-03"))
    with laptops.db() as c:
        assert c.execute("SELECT signed_on FROM assignments WHERE id=2").fetchone()[0] == "2026-04-03"


def test_cmd_assign_unknown_student_or_laptop():
    laptops.cmd_add_laptop(ns(tag="X1", model="M", serial="S", value=0))
    with pytest.raises(SystemExit):
        laptops.cmd_assign(ns(student_no="nope", tag="X1", date=None))
    laptops.cmd_add_student(ns(name="Ann", student_no="5", grade=None, guardian=None, guardian_email=None, id_number=None))
    with pytest.raises(SystemExit):
        laptops.cmd_assign(ns(student_no="5", tag="nope", date=None))


def test_cmd_available_and_list(capsys):
    laptops.cmd_add_student(ns(name="Ann", student_no="5", grade="10", guardian=None, guardian_email=None, id_number=None))
    laptops.cmd_add_laptop(ns(tag="X1", model="M1", serial="S1", value=0))
    laptops.cmd_add_laptop(ns(tag="X2", model="M2", serial="S2", value=0))
    laptops.cmd_assign(ns(student_no="5", tag="X1", date="2026-03-01"))
    capsys.readouterr()
    laptops.cmd_available(ns())
    out = capsys.readouterr().out
    assert "X2" in out and "X1" not in out
    laptops.cmd_list(ns(all=False))
    assert "Ann" in capsys.readouterr().out
    laptops.cmd_return(ns(tag="X1", date="2026-03-05"))
    capsys.readouterr()
    laptops.cmd_list(ns(all=False))
    assert "Ann" not in capsys.readouterr().out
    laptops.cmd_list(ns(all=True))
    assert "Ann" in capsys.readouterr().out
