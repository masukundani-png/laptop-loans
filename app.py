#!/usr/bin/env python3
"""Tiny web UI for the laptop loan tracker. Run: python3 app.py  then open http://localhost:8000"""
import html, os, sqlite3, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import laptops

e = lambda v: html.escape(str(v if v is not None else ""))

PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Laptop Loans</title><style>
 body{{font:15px system-ui,sans-serif;max-width:860px;margin:24px auto;padding:0 16px;color:#222}}
 h1{{font-size:22px}} h2{{font-size:16px;margin:0 0 8px}}
 .card{{border:1px solid #ddd;border-radius:8px;padding:14px;margin:14px 0}}
 form{{display:flex;flex-wrap:wrap;gap:8px;align-items:center}}
 input,select{{padding:7px;border:1px solid #bbb;border-radius:5px;font:inherit}}
 button{{padding:7px 14px;border:0;border-radius:5px;background:#e8591a;color:#fff;font:inherit;cursor:pointer}}
 table{{width:100%;border-collapse:collapse}} td,th{{text-align:left;padding:5px 6px;border-bottom:1px solid #eee}}
 .msg{{background:#e9f7ec;border:1px solid #9fd6aa;padding:8px 12px;border-radius:6px}}
 .err{{background:#fdecec;border-color:#e3a0a0}}
</style></head><body>
<h1>Laptop Loans</h1>{msg}
<div class="card"><h2>Add a student</h2>
<form method="post" action="/add-student">
 <input name="name" placeholder="Full name and surname" required size="28">
 <input name="student_no" placeholder="Student number" required>
 <input name="id_number" placeholder="ID / passport">
 <button>Add student</button></form></div>
<div class="card"><h2>Import students from CSV</h2>
<form class="csvform" data-url="/import-csv"><input type="file" accept=".csv,text/csv" required>
 <button>Import</button> <a href="/sample.csv">Download sample CSV</a></form>
<p style="margin:6px 0 0;color:#666;font-size:13px">Columns: Name, Student Number, ID/Passport. Existing student numbers are skipped.</p></div>
<div class="card"><h2>Import laptops from CSV</h2>
<form class="csvform" data-url="/import-laptops-csv"><input type="file" accept=".csv,text/csv" required>
 <button>Import</button> <a href="/sample-laptops.csv">Download sample CSV</a></form>
<p style="margin:6px 0 0;color:#666;font-size:13px">Columns: Asset Tag, Model, Serial Number. Existing asset tags are skipped.</p></div>
<script>
document.querySelectorAll('.csvform').forEach(f=>f.onsubmit=async e=>{{e.preventDefault();
 const t=await f.querySelector('input').files[0].text();
 const r=await fetch(f.dataset.url,{{method:'POST',body:t}});
 document.open();document.write(await r.text());document.close();}});
</script>
<div class="card"><h2>Add a laptop</h2>
<form method="post" action="/add-laptop">
 <input name="tag" placeholder="Asset tag" required>
 <input name="model" placeholder="Model" value="Lenovo V15 GEN 2 IJL" size="22">
 <input name="serial" placeholder="Serial number" required>
 <button>Add laptop</button></form></div>
<div class="card"><h2>Assign a laptop &amp; create the form</h2>
<form method="post" action="/assign">
 <select name="student_no" required><option value="">Student…</option>{students}</select>
 <select name="tag" required><option value="">Laptop…</option>{avail}</select>
 <button>Assign</button></form></div>
<div class="card"><h2>Students ({n_students})</h2>
<table><tr><th>Name</th><th>Student no.</th><th>ID/Passport</th><th>Laptop</th><th>Form</th></tr>{rows}</table></div>
</body></html>"""

def form_link(student_no, tag):
    base = f"loan_agreement_{student_no}_{tag}"
    ext = "pdf" if os.path.exists(os.path.join(laptops.OUT, base + ".pdf")) else "docx"
    return f"<a href='/contracts/{urllib.parse.quote(base)}.{ext}'>{ext.upper()}</a>"

def render(msg="", err=False):
    with laptops.db() as c:
        studs = c.execute("""SELECT s.*, (SELECT l.asset_tag||' ('||a.issued_on||')' FROM assignments a
              JOIN laptops l ON l.id=a.laptop_id WHERE a.student_id=s.id AND a.returned_on IS NULL) loan,
              (SELECT l.asset_tag FROM assignments a JOIN laptops l ON l.id=a.laptop_id
               WHERE a.student_id=s.id AND a.returned_on IS NULL) tag FROM students s ORDER BY s.id DESC""").fetchall()
        avail = c.execute("""SELECT asset_tag, model FROM laptops WHERE id NOT IN
              (SELECT laptop_id FROM assignments WHERE returned_on IS NULL) ORDER BY asset_tag""").fetchall()
    rows = "".join(
        f"<tr><td>{e(s['name'])}</td><td>{e(s['student_no'])}</td><td>{e(s['id_number'])}</td>"
        f"<td>{e(s['loan']) or '–'}</td><td>" +
        (form_link(s["student_no"], s["tag"]) if s["tag"] else "") + "</td></tr>" for s in studs)
    return PAGE.format(
        msg=f"<p class='msg {'err' if err else ''}'>{e(msg)}</p>" if msg else "",
        students="".join(f"<option value='{e(s['student_no'])}'>{e(s['name'])} ({e(s['student_no'])})</option>" for s in studs),
        avail="".join(f"<option value='{e(l['asset_tag'])}'>{e(l['asset_tag'])} – {e(l['model'])}</option>" for l in avail),
        n_students=len(studs), rows=rows or "<tr><td colspan=5>No students yet.</td></tr>")

class H(BaseHTTPRequestHandler):
    def send(self, body, ctype="text/html; charset=utf-8", code=200):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/contracts/"):
            f = os.path.join(laptops.OUT, os.path.basename(urllib.parse.unquote(path)))
            if os.path.isfile(f):
                ct = "application/pdf" if f.endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                return self.send(open(f, "rb").read(), ct)
            return self.send("Not found", "text/plain", 404)
        if path == "/sample-laptops.csv":
            return self.send("Asset Tag,Model,Serial Number\nLT-001,Lenovo V15 GEN 2 IJL,PF5X3HNC\n", "text/csv")
        if path == "/sample.csv":
            return self.send("Name,Student Number,ID/Passport\nAmara Okafor,222012345,0501015800087\n", "text/csv")
        self.send(render())

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        if self.path in ("/import-csv", "/import-laptops-csv"):
            students = self.path == "/import-csv"
            fn = laptops.import_students if students else laptops.import_laptops
            added, skipped, problems = fn(self.rfile.read(n).decode("utf-8", "replace"))
            msg = f"Imported {added} {'students' if students else 'laptops'}."
            if skipped: msg += f" Skipped {len(skipped)} already in the database: " + ", ".join(skipped[:10]) + ("…" if len(skipped) > 10 else "") + "."
            if problems: msg += " Problems: " + " ".join(problems[:5])
            return self.send(render(msg, bool(problems) and not added))
        f = {k: v[0].strip() for k, v in urllib.parse.parse_qs(self.rfile.read(n).decode()).items()}
        try:
            if self.path == "/add-student":
                with laptops.db() as c:
                    c.execute("INSERT INTO students(name,student_no,id_number) VALUES(?,?,?)",
                              (f["name"], f["student_no"], f.get("id_number")))
                msg = f"Added {f['name']}."
            elif self.path == "/add-laptop":
                with laptops.db() as c:
                    c.execute("INSERT INTO laptops(asset_tag,model,serial) VALUES(?,?,?)",
                              (f["tag"], f.get("model"), f["serial"]))
                msg = f"Added laptop {f['tag']}."
            elif self.path == "/assign":
                with laptops.db() as c:
                    s = c.execute("SELECT id FROM students WHERE student_no=?", (f["student_no"],)).fetchone()
                    l = c.execute("SELECT id FROM laptops WHERE asset_tag=?", (f["tag"],)).fetchone()
                    cur = c.execute("INSERT INTO assignments(student_id,laptop_id,issued_on) VALUES(?,?,date('now'))",
                                    (s["id"], l["id"]))
                laptops.make_contract(cur.lastrowid)
                msg = f"Assigned {f['tag']} to {f['student_no']}. Form created, see the PDF link below."
            else:
                return self.send("Not found", "text/plain", 404)
            self.send(render(msg))
        except sqlite3.IntegrityError:
            self.send(render("That student number or asset tag already exists, or the laptop is already assigned.", True))
        except (KeyError, TypeError):
            self.send(render("Please fill in the required fields.", True))

if __name__ == "__main__":
    print("Open http://localhost:8000")
    ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
