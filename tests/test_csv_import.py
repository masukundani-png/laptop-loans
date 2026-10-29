import pytest
import laptops


def students():
    with laptops.db() as c:
        return [tuple(r) for r in c.execute("SELECT name,student_no,id_number FROM students ORDER BY id")]


def lapt():
    with laptops.db() as c:
        return [tuple(r) for r in c.execute("SELECT asset_tag,model,serial FROM laptops ORDER BY id")]


# ---------- students ----------

def test_students_comma():
    r = laptops.import_students("name,student_no,id_number\nAnn Lee,1,8001\nBob Ray,2,8002\n")
    assert r == (2, [], [])
    assert students() == [("Ann Lee", "1", "8001"), ("Bob Ray", "2", "8002")]


def test_students_semicolon():
    r = laptops.import_students("Student Name and Surname;Student Number;Student ID/Passport\nAnn Lee;1;8001\nBob Ray;2;8002\n")
    assert r == (2, [], [])
    assert students()[1] == ("Bob Ray", "2", "8002")


def test_students_bom():
    r = laptops.import_students("﻿name,student_no\nAnn,1\n")
    assert r[0] == 1 and r[2] == []


def test_students_header_aliases_case_and_spaces():
    r = laptops.import_students(" Full Name , STUDENT NUMBER , Passport \nAnn,1,P123\n")
    assert r == (1, [], [])
    assert students() == [("Ann", "1", "P123")]


def test_students_id_column_optional():
    assert laptops.import_students("name,student_no\nAnn,1\n")[0] == 1
    assert students() == [("Ann", "1", "")]


def test_students_duplicates_skipped():
    laptops.import_students("name,student_no\nAnn,1\n")
    added, skipped, problems = laptops.import_students("name,student_no\nAnn Again,1\nNew,2\nNew2,2\n")
    assert added == 1
    assert skipped == ["Ann Again (1)", "New2 (2)"]
    assert problems == []
    assert len(students()) == 2


def test_students_duplicates_within_same_file():
    added, skipped, _ = laptops.import_students("name,student_no\nA,1\nB,1\n")
    assert added == 1 and len(skipped) == 1


def test_students_missing_fields_reported_with_row_numbers():
    added, skipped, problems = laptops.import_students("name,student_no\nAnn,\n,2\nOk,3\n")
    assert added == 1 and skipped == []
    assert problems == ["Row 2: missing name or student number.", "Row 3: missing name or student number."]


def test_students_short_row_treated_as_missing():
    added, _, problems = laptops.import_students("name,student_no,id_number\nAnn\nBob,2\n")
    assert added == 1
    assert len(problems) == 1 and problems[0].startswith("Row 2")


def test_students_missing_header():
    added, skipped, problems = laptops.import_students("foo,bar\n1,2\n")
    assert added == 0 and skipped == []
    assert len(problems) == 1 and "missing" in problems[0] and "name" in problems[0]
    assert students() == []


def test_students_missing_only_one_header():
    _, _, problems = laptops.import_students("name,other\nAnn,1\n")
    assert "student_no" in problems[0] and "name," not in problems[0].split("Found")[0]


@pytest.mark.parametrize("text", ["", "﻿"])
def test_students_empty_file(text):
    assert laptops.import_students(text) == (0, [], ["The file is empty."])


def test_students_header_only():
    assert laptops.import_students("name,student_no\n") == (0, [], [])


def test_students_blank_lines_ignored():
    added, _, problems = laptops.import_students("name,student_no\n\nAnn,1\n\n   \n,\nBob,2\n\n")
    assert added == 2 and problems == []


def test_students_crlf_and_whitespace_trimmed():
    laptops.import_students("name,student_no\r\n  Ann  , 1 \r\n")
    assert students() == [("Ann", "1", "")]


def test_students_quoted_comma_in_name():
    laptops.import_students('name,student_no\n"Lee, Ann",1\n')
    assert students()[0][0] == "Lee, Ann"


def test_students_tab_delimited():
    assert laptops.import_students("name\tstudent_no\nAnn\t1\nBob\t2\n")[0] == 2


# ---------- laptops ----------

def test_laptops_comma():
    r = laptops.import_laptops("asset_tag,model,serial\nLT1,Dell,S1\nLT2,HP,S2\n")
    assert r == (2, [], [])
    assert lapt() == [("LT1", "Dell", "S1"), ("LT2", "HP", "S2")]


def test_laptops_semicolon_bom_aliases():
    r = laptops.import_laptops("﻿Asset Tag;Device Model;Serial Number\nLT1;Dell 3420;S1\n")
    assert r == (1, [], [])
    assert lapt() == [("LT1", "Dell 3420", "S1")]


def test_laptops_model_optional():
    assert laptops.import_laptops("tag,serial\nLT1,S1\n")[0] == 1
    assert lapt() == [("LT1", "", "S1")]


def test_laptops_duplicates_skipped():
    laptops.import_laptops("tag,serial\nLT1,S1\n")
    added, skipped, problems = laptops.import_laptops("tag,serial\nLT1,S9\nLT2,S2\n")
    assert (added, skipped, problems) == (1, ["LT1"], [])


def test_laptops_missing_fields():
    added, _, problems = laptops.import_laptops("tag,model,serial\nLT1,Dell,\n,HP,S2\nLT3,HP,S3\n")
    assert added == 1
    assert problems == ["Row 2: missing asset tag or serial number.", "Row 3: missing asset tag or serial number."]


def test_laptops_missing_header():
    added, _, problems = laptops.import_laptops("tag,model\nLT1,Dell\n")
    assert added == 0 and "serial" in problems[0]


def test_laptops_empty_file():
    assert laptops.import_laptops("") == (0, [], ["The file is empty."])


def test_laptops_blank_lines():
    added, _, problems = laptops.import_laptops("tag,serial\n\nLT1,S1\n\n\nLT2,S2\n")
    assert added == 2 and problems == []


# ---------- CLI wrapper ----------

def test_cmd_import_reads_file_with_bom(tmp_path, capsys):
    import argparse
    f = tmp_path / "s.csv"
    f.write_bytes("﻿name;student_no\nAnn;1\nAnn;1\n".encode("utf-8"))
    laptops.cmd_import(argparse.Namespace(file=str(f)))
    out = capsys.readouterr().out
    assert "Added 1 students." in out and "Skipped 1" in out
