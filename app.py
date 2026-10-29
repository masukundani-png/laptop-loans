#!/usr/bin/env python3
"""Web UI for the laptop loan tracker (password protected).

Run:  python3 app.py            then open http://127.0.0.1:8000
      python3 app.py --host 0.0.0.0 --port 8080   (LAN access; there is NO TLS, see warning)
      python3 app.py --set-password               set/reset the password from the terminal

The first visit asks you to create a password. Only a salted PBKDF2-HMAC-SHA256 hash is stored,
in config.json next to this file. The env var LAPTOP_LOANS_PASSWORD overrides the stored password.
"""
import argparse, getpass, hashlib, hmac, html, json, os, re, secrets, sqlite3, sys, threading, time
import urllib.parse
from datetime import date
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import laptops

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
ITERATIONS = 310_000          # PBKDF2-HMAC-SHA256 iterations for newly stored hashes (>= 200k)
MIN_PASSWORD = 8
MAX_PASSWORD = 256
MAX_BODY = 2 * 1024 * 1024    # 2 MB request body cap
SESSION_TTL = 8 * 3600        # 8 hours
MAX_FAILS, LOCK_SECONDS = 5, 60
COOKIE, PRE_COOKIE = "ll_session", "ll_pre"
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")   # student numbers and asset tags
LOOPBACK = ("127.0.0.1", "::1")

e = lambda v: html.escape(str(v if v is not None else ""))

# ---------------------------------------------------------------- password storage
_cfg_lock = threading.Lock()

def _hash(password, salt, iterations):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)

def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}

def save_password(password):
    salt = secrets.token_bytes(16)
    data = {"password": {"algo": "pbkdf2_sha256", "iterations": ITERATIONS,
                         "salt": salt.hex(), "hash": _hash(password, salt, ITERATIONS).hex()}}
    tmp = CONFIG + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    try: os.chmod(tmp, 0o600)
    except OSError: pass
    os.replace(tmp, CONFIG)

def env_password():
    return os.environ.get("LAPTOP_LOANS_PASSWORD") or None

def has_password():
    return bool(env_password() or load_config().get("password"))

def verify_password(password):
    env = env_password()
    if env:
        return hmac.compare_digest(password.encode("utf-8"), env.encode("utf-8"))
    p = load_config().get("password")
    try:
        salt, want, it = bytes.fromhex(p["salt"]), bytes.fromhex(p["hash"]), int(p["iterations"])
    except (TypeError, KeyError, ValueError):
        return False
    return hmac.compare_digest(_hash(password, salt, it), want)

# ---------------------------------------------------------------- sessions and throttling
_lock = threading.Lock()
SESSIONS = {}     # token -> {"csrf": str, "exp": float}
FAILS = {}        # ip -> [count, locked_until]

def reset_state():
    with _lock:
        SESSIONS.clear(); FAILS.clear()

def new_session():
    tok, now = secrets.token_urlsafe(32), time.time()
    with _lock:
        for k in [k for k, v in SESSIONS.items() if v["exp"] <= now]: del SESSIONS[k]
        SESSIONS[tok] = {"csrf": secrets.token_urlsafe(32), "exp": now + SESSION_TTL}
    return tok

def get_session(tok):
    if not tok: return None
    with _lock:
        for k, v in SESSIONS.items():
            if hmac.compare_digest(k, tok):
                if v["exp"] > time.time(): return v
                del SESSIONS[k]; return None
    return None

def drop_session(tok):
    with _lock:
        for k in list(SESSIONS):
            if tok and hmac.compare_digest(k, tok): del SESSIONS[k]

def lock_remaining(ip):
    with _lock:
        f = FAILS.get(ip)
        return max(0, int(f[1] - time.time() + 0.999)) if f and f[1] > time.time() else 0

def record_fail(ip):
    with _lock:
        f = FAILS.setdefault(ip, [0, 0.0])
        if f[1] and f[1] <= time.time(): f[0], f[1] = 0, 0.0
        f[0] += 1
        if f[0] >= MAX_FAILS: f[1] = time.time() + LOCK_SECONDS

def record_ok(ip):
    with _lock: FAILS.pop(ip, None)

# ---------------------------------------------------------------- pages
STYLE = """
 body{font:15px system-ui,sans-serif;max-width:860px;margin:24px auto;padding:0 16px;color:#222}
 h1{font-size:22px} h2{font-size:16px;margin:0 0 8px}
 .card{border:1px solid #ddd;border-radius:8px;padding:14px;margin:14px 0}
 form{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
 input,select{padding:7px;border:1px solid #bbb;border-radius:5px;font:inherit}
 button{padding:7px 14px;border:0;border-radius:5px;background:#e8591a;color:#fff;font:inherit;cursor:pointer}
 button.small{padding:3px 9px;font-size:13px} button.alt{background:#555}
 table{width:100%;border-collapse:collapse} td,th{text-align:left;padding:5px 6px;border-bottom:1px solid #eee;vertical-align:middle}
 td form{display:inline-flex;margin:0 4px 0 0}
 .msg{background:#e9f7ec;border:1px solid #9fd6aa;padding:8px 12px;border-radius:6px}
 .err{background:#fdecec;border-color:#e3a0a0}
 .hint{margin:6px 0 0;color:#666;font-size:13px}
 .top{display:flex;justify-content:space-between;align-items:center}
 .narrow{max-width:380px}
"""

PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="csrf-token" content="@@csrf@@"><title>Laptop Loans</title><style nonce="@@nonce@@">@@style@@</style></head><body>
<div class="top"><h1>Laptop Loans</h1>
<form method="post" action="/logout"><input type="hidden" name="csrf_token" value="@@csrf@@"><button class="small alt">Log out</button></form></div>@@msg@@
<div class="card"><h2>Add a student</h2>
<form method="post" action="/add-student"><input type="hidden" name="csrf_token" value="@@csrf@@">
 <input name="name" placeholder="Full name and surname" required size="28" maxlength="200">
 <input name="student_no" placeholder="Student number" required maxlength="64" pattern="[A-Za-z0-9._\\-]+" title="Letters, digits, - _ . only">
 <input name="id_number" placeholder="ID / passport" maxlength="64">
 <button>Add student</button></form></div>
<div class="card"><h2>Import students from CSV</h2>
<form class="csvform" data-url="/import-csv"><input type="file" accept=".csv,text/csv" required>
 <button>Import</button> <a href="/sample.csv">Download sample CSV</a></form>
<p class="hint">Columns: Name, Student Number, ID/Passport. Existing student numbers are skipped.</p></div>
<div class="card"><h2>Import laptops from CSV</h2>
<form class="csvform" data-url="/import-laptops-csv"><input type="file" accept=".csv,text/csv" required>
 <button>Import</button> <a href="/sample-laptops.csv">Download sample CSV</a></form>
<p class="hint">Columns: Asset Tag, Model, Serial Number. Existing asset tags are skipped.</p></div>
<script nonce="@@nonce@@">
document.addEventListener('submit',async ev=>{const f=ev.target;if(!f.classList||!f.classList.contains('csvform'))return;
 ev.preventDefault();
 const t=await f.querySelector('input[type=file]').files[0].text();
 const tok=document.querySelector('meta[name=csrf-token]').content;
 const r=await fetch(f.dataset.url,{method:'POST',body:t,headers:{'X-CSRF-Token':tok},credentials:'same-origin'});
 if(r.redirected){location.href=r.url;return;}
 const d=new DOMParser().parseFromString((await r.text()).replace(/<style[\s\S]*?<\/style>/g,''),'text/html');
 document.body.innerHTML=d.body.innerHTML;window.scrollTo(0,0);});
</script>
<div class="card"><h2>Add a laptop</h2>
<form method="post" action="/add-laptop"><input type="hidden" name="csrf_token" value="@@csrf@@">
 <input name="tag" placeholder="Asset tag" required maxlength="64" pattern="[A-Za-z0-9._\\-]+" title="Letters, digits, - _ . only">
 <input name="model" placeholder="Model" value="Lenovo V15 GEN 2 IJL" size="22" maxlength="200">
 <input name="serial" placeholder="Serial number" required maxlength="100">
 <button>Add laptop</button></form></div>
<div class="card"><h2>Assign a laptop &amp; create the form</h2>
<form method="post" action="/assign"><input type="hidden" name="csrf_token" value="@@csrf@@">
 <select name="student_no" required><option value="">Student…</option>@@students@@</select>
 <select name="tag" required><option value="">Laptop…</option>@@avail@@</select>
 <button>Assign</button></form></div>
<div class="card"><h2>Students (@@n_students@@)</h2>
<table><tr><th>Name</th><th>Student no.</th><th>ID/Passport</th><th>Laptop</th><th>Form</th><th>Actions</th></tr>@@rows@@</table></div>
</body></html>"""

AUTH_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>@@title@@</title><style nonce="@@nonce@@">@@style@@</style></head><body class="narrow">
<h1>@@title@@</h1>@@msg@@<div class="card"><form method="post" action="@@action@@">
<input type="hidden" name="csrf_token" value="@@csrf@@">@@fields@@<button>@@button@@</button></form></div></body></html>"""

def fill(tpl, **vals):
    return re.sub(r"@@(\w+)@@", lambda m: vals[m.group(1)], tpl)   # single pass: values are never re-scanned

def msg_html(msg, err=False):
    return f"<p class='msg {'err' if err else ''}'>{e(msg)}</p>" if msg else ""

def form_link(student_no, tag):
    base = f"loan_agreement_{student_no}_{tag}"
    ext = "pdf" if os.path.exists(os.path.join(laptops.OUT, base + ".pdf")) else "docx"
    return f"<a href='/contracts/{e(urllib.parse.quote(base))}.{ext}'>{ext.upper()}</a>"

def render(csrf, nonce, msg="", err=False):
    with laptops.db() as c:
        studs = c.execute("""SELECT s.*,
              (SELECT l.asset_tag||' ('||a.issued_on||')' FROM assignments a
                 JOIN laptops l ON l.id=a.laptop_id WHERE a.student_id=s.id AND a.returned_on IS NULL) loan,
              (SELECT l.asset_tag FROM assignments a JOIN laptops l ON l.id=a.laptop_id
                 WHERE a.student_id=s.id AND a.returned_on IS NULL) tag,
              (SELECT a.signed_on FROM assignments a
                 WHERE a.student_id=s.id AND a.returned_on IS NULL) signed
              FROM students s ORDER BY s.id DESC""").fetchall()
        avail = c.execute("""SELECT asset_tag, model FROM laptops WHERE id NOT IN
              (SELECT laptop_id FROM assignments WHERE returned_on IS NULL) ORDER BY asset_tag""").fetchall()
    hid = f"<input type='hidden' name='csrf_token' value='{e(csrf)}'>"
    def actions(s):
        if not s["tag"]: return ""
        out = (f"<form method='post' action='/return'>{hid}<input type='hidden' name='tag' value='{e(s['tag'])}'>"
               f"<button class='small alt'>Return</button></form>")
        if s["signed"]: out += f"<small>Signed {e(s['signed'])}</small>"
        else:
            out += (f"<form method='post' action='/signed'>{hid}<input type='hidden' name='student_no' value='{e(s['student_no'])}'>"
                    f"<button class='small'>Mark signed</button></form>")
        return out
    rows = "".join(
        f"<tr><td>{e(s['name'])}</td><td>{e(s['student_no'])}</td><td>{e(s['id_number'])}</td>"
        f"<td>{e(s['loan']) or '–'}</td><td>" +
        (form_link(s["student_no"], s["tag"]) if s["tag"] else "") + f"</td><td>{actions(s)}</td></tr>" for s in studs)
    return fill(PAGE, nonce=e(nonce), csrf=e(csrf), style=STYLE, msg=msg_html(msg, err),
        students="".join(f"<option value='{e(s['student_no'])}'>{e(s['name'])} ({e(s['student_no'])})</option>" for s in studs),
        avail="".join(f"<option value='{e(l['asset_tag'])}'>{e(l['asset_tag'])} – {e(l['model'])}</option>" for l in avail),
        n_students=str(len(studs)), rows=rows or "<tr><td colspan=6>No students yet.</td></tr>")

def auth_page(nonce, csrf, kind, msg="", err=True):
    if kind == "login":
        fields = "<input type='password' name='password' placeholder='Password' required autofocus maxlength='256'>"
        a = dict(title="Log in", action="/login", button="Log in")
    else:
        fields = ("<input type='password' name='password' placeholder='New password (min 8 characters)' required minlength='8' maxlength='256'>"
                  "<input type='password' name='confirm' placeholder='Confirm password' required minlength='8' maxlength='256'>")
        a = dict(title="Create a password", action="/setup", button="Save password")
    return fill(AUTH_PAGE, nonce=e(nonce), csrf=e(csrf), style=STYLE, msg=msg_html(msg, err), fields=fields, **a)

# ---------------------------------------------------------------- request handling
class H(BaseHTTPRequestHandler):
    timeout = 30
    server_version = "LaptopLoans"
    sys_version = ""

    # -- helpers
    def send(self, body, ctype="text/html; charset=utf-8", code=200, headers=(), nonce=None, cache=True):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        csp = "default-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; connect-src 'self'; img-src 'self'"
        if nonce: csp += f"; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'"
        self.send_header("Content-Security-Policy", csp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        for k, v in headers: self.send_header(k, v)
        self.end_headers(); self.wfile.write(b)

    def redirect(self, where, headers=()):
        self.send("", "text/plain", 303, headers=[("Location", where), *headers])

    def text(self, msg, code): self.send(msg, "text/plain; charset=utf-8", code)

    def cookie(self, name):
        try: c = SimpleCookie(self.headers.get("Cookie", ""))
        except Exception: return None
        return c[name].value if name in c else None

    def ip(self): return self.client_address[0]

    def cookie_hdr(self, name, val, max_age):
        return ("Set-Cookie", f"{name}={val}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max_age}")

    def session(self): return get_session(self.cookie(COOKIE))

    def read_body(self):
        """Return body bytes, or None after having sent an error response."""
        if self.headers.get("Transfer-Encoding"):
            self.text("Chunked bodies are not supported.", 411); return None
        try: n = int(self.headers.get("Content-Length", 0))
        except ValueError: n = -1
        if n < 0: self.text("Bad Content-Length.", 400); return None
        if n > MAX_BODY: self.text("Request too large (limit 2 MB).", 413); return None
        return self.rfile.read(n)

    def csrf_ok(self, sess, form=None):
        got = self.headers.get("X-CSRF-Token") or (form or {}).get("csrf_token") or ""
        return hmac.compare_digest(got.encode(), sess["csrf"].encode())

    def pre_token(self):
        """Anonymous CSRF token for the login/setup forms (double-submit cookie)."""
        return self.cookie(PRE_COOKIE) or secrets.token_urlsafe(24)

    def auth_form(self, kind, msg="", err=True, code=200):
        pre, nonce = self.pre_token(), secrets.token_urlsafe(16)
        self.send(auth_page(nonce, pre, kind, msg, err), code=code, nonce=nonce,
                  headers=[self.cookie_hdr(PRE_COOKIE, pre, 3600)])

    def start_session(self, where="/"):
        tok = new_session()
        self.redirect(where, [self.cookie_hdr(COOKIE, tok, SESSION_TTL), self.cookie_hdr(PRE_COOKIE, "", 0)])

    # -- GET
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/login":
            if not has_password(): return self.redirect("/setup")
            return self.auth_form("login")
        if path == "/setup":
            if has_password(): return self.redirect("/login")
            if self.ip() not in LOOPBACK:
                return self.text("Create the password on the server computer: python3 app.py --set-password", 403)
            return self.auth_form("setup", "Choose a password to protect student data.", False)
        if not has_password(): return self.redirect("/setup")
        sess = self.session()
        if not sess: return self.redirect("/login")
        if path.startswith("/contracts/"):
            name = os.path.basename(urllib.parse.unquote(path))
            f = os.path.join(laptops.OUT, name)
            ok = (name and "\x00" not in name and name.lower().endswith((".pdf", ".docx"))
                  and os.path.isfile(f)
                  and os.path.realpath(f).startswith(os.path.realpath(laptops.OUT) + os.sep))
            if not ok: return self.text("Not found", 404)
            ct = "application/pdf" if name.lower().endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            with open(f, "rb") as fh: data = fh.read()
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)
            return self.send(data, ct, headers=[("Content-Disposition", f'attachment; filename="{safe}"')])
        if path == "/sample-laptops.csv":
            return self.send("Asset Tag,Model,Serial Number\nLT-001,Lenovo V15 GEN 2 IJL,PF5X3HNC\n", "text/csv")
        if path == "/sample.csv":
            return self.send("Name,Student Number,ID/Passport\nAmara Okafor,222012345,0501015800087\n", "text/csv")
        if path != "/": return self.text("Not found", 404)
        nonce = secrets.token_urlsafe(16)
        self.send(render(sess["csrf"], nonce), nonce=nonce)

    # -- POST
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        body = self.read_body()
        if body is None: return
        if path in ("/login", "/setup"): return self.post_auth(path, body)
        if not has_password(): return self.redirect("/setup")
        sess = self.session()
        if not sess: return self.redirect("/login")
        csv_route = path in ("/import-csv", "/import-laptops-csv")
        form = {} if csv_route else {k: v[0].strip() for k, v in
                urllib.parse.parse_qs(body.decode("utf-8", "replace")).items() if v}
        if not self.csrf_ok(sess, form): return self.text("Forbidden: missing or invalid CSRF token.", 403)
        if path == "/logout":
            drop_session(self.cookie(COOKIE))
            return self.redirect("/login", [self.cookie_hdr(COOKIE, "", 0)])
        nonce, csrf = secrets.token_urlsafe(16), sess["csrf"]
        def page(msg, err=False, code=200): self.send(render(csrf, nonce, msg, err), code=code, nonce=nonce)
        if csv_route: return self.post_csv(path, body, page)
        try:
            msg = self.post_action(path, form)
            if msg is None: return self.text("Not found", 404)
            page(msg)
        except sqlite3.IntegrityError:
            page("That student number or asset tag already exists, or the laptop is already assigned.", True)
        except ValueError as x:
            page(str(x), True)
        except (KeyError, TypeError):
            page("Please fill in the required fields.", True)

    def post_auth(self, path, body):
        f = {k: v[0] for k, v in urllib.parse.parse_qs(body.decode("utf-8", "replace")).items() if v}
        pre = self.cookie(PRE_COOKIE) or ""
        if not pre or not hmac.compare_digest(f.get("csrf_token", "").encode(), pre.encode()):
            return self.text("Forbidden: missing or invalid CSRF token.", 403)
        pw = f.get("password", "")
        if path == "/setup":
            if self.ip() not in LOOPBACK:
                return self.text("Create the password on the server computer: python3 app.py --set-password", 403)
            with _cfg_lock:
                if has_password(): return self.redirect("/login")
                if len(pw) < MIN_PASSWORD: return self.auth_form("setup", f"Password must be at least {MIN_PASSWORD} characters.", code=400)
                if len(pw) > MAX_PASSWORD: return self.auth_form("setup", "Password is too long.", code=400)
                if not hmac.compare_digest(pw.encode(), f.get("confirm", "").encode()):
                    return self.auth_form("setup", "The two passwords do not match.", code=400)
                save_password(pw)
            return self.start_session()
        if not has_password(): return self.redirect("/setup")
        wait = lock_remaining(self.ip())
        if wait:
            self.send(f"Too many failed attempts. Try again in {wait} seconds.", "text/plain; charset=utf-8", 429,
                      headers=[("Retry-After", str(wait))]); return
        if len(pw) <= MAX_PASSWORD and verify_password(pw):
            record_ok(self.ip()); return self.start_session()
        record_fail(self.ip())
        wait = lock_remaining(self.ip())
        if wait:
            self.send(f"Too many failed attempts. Try again in {wait} seconds.", "text/plain; charset=utf-8", 429,
                      headers=[("Retry-After", str(wait))]); return
        self.auth_form("login", "Incorrect password.", code=401)

    def post_csv(self, path, body, page):
        students = path == "/import-csv"
        text = body.decode("utf-8", "replace")
        fn = laptops.import_students if students else laptops.import_laptops
        # reject unsafe student numbers / asset tags before touching the DB (they become file names)
        al, req, key = ((laptops.ALIASES, ["name", "student_no"], "student_no") if students
                        else (laptops.LAPTOP_ALIASES, ["tag", "serial"], "tag"))
        rows, err = laptops.read_csv(text, al, req)
        if not err:
            bad = [str(n) for n, r in rows if r[key] and not SAFE_ID.match(r[key])]
            if bad:
                return page("Nothing imported. Row(s) " + ", ".join(bad[:10]) +
                            " have a " + ("student number" if students else "asset tag") +
                            " with characters other than letters, digits, - _ .", True)
        added, skipped, problems = fn(text)
        msg = f"Imported {added} {'students' if students else 'laptops'}."
        if skipped: msg += f" Skipped {len(skipped)} already in the database: " + ", ".join(skipped[:10]) + ("…" if len(skipped) > 10 else "") + "."
        if problems: msg += " Problems: " + " ".join(problems[:5])
        page(msg, bool(problems) and not added)

    def post_action(self, path, f):
        """Handle the simple form actions. Returns a message, or None for an unknown route."""
        if path == "/add-student":
            if not SAFE_ID.match(f["student_no"]):
                raise ValueError("Student number may only contain letters, digits, - _ . (max 64).")
            if not f["name"] or len(f["name"]) > 200: raise KeyError("name")
            with laptops.db() as c:
                c.execute("INSERT INTO students(name,student_no,id_number) VALUES(?,?,?)",
                          (f["name"], f["student_no"], f.get("id_number")))
            return f"Added {f['name']}."
        if path == "/add-laptop":
            if not SAFE_ID.match(f["tag"]):
                raise ValueError("Asset tag may only contain letters, digits, - _ . (max 64).")
            with laptops.db() as c:
                c.execute("INSERT INTO laptops(asset_tag,model,serial) VALUES(?,?,?)",
                          (f["tag"], f.get("model"), f["serial"]))
            return f"Added laptop {f['tag']}."
        if path == "/assign":
            with laptops.db() as c:
                s = c.execute("SELECT id FROM students WHERE student_no=?", (f["student_no"],)).fetchone()
                l = c.execute("SELECT id FROM laptops WHERE asset_tag=?", (f["tag"],)).fetchone()
                if not s or not l: raise ValueError("Unknown student or laptop.")
                cur = c.execute("INSERT INTO assignments(student_id,laptop_id,issued_on) VALUES(?,?,date('now'))",
                                (s["id"], l["id"]))
            try:
                laptops.make_contract(cur.lastrowid)
            except BaseException as x:   # make_contract may sys.exit() or fail on missing docx/template
                return f"Assigned {f['tag']} to {f['student_no']}, but the form could not be created ({type(x).__name__})."
            return f"Assigned {f['tag']} to {f['student_no']}. Form created, see the link below."
        if path == "/return":     # same SQL as laptops.cmd_return
            with laptops.db() as c:
                n = c.execute("UPDATE assignments SET returned_on=? WHERE returned_on IS NULL AND laptop_id="
                              "(SELECT id FROM laptops WHERE asset_tag=?)",
                              (date.today().isoformat(), f["tag"])).rowcount
            if not n: raise ValueError("That laptop is not currently assigned.")
            return f"Returned {f['tag']}."
        if path == "/signed":     # same SQL as laptops.cmd_signed, for the student's open assignment
            with laptops.db() as c:
                n = c.execute("UPDATE assignments SET signed_on=? WHERE id=(SELECT a.id FROM assignments a "
                              "JOIN students s ON s.id=a.student_id WHERE s.student_no=? AND a.returned_on IS NULL)",
                              (date.today().isoformat(), f["student_no"])).rowcount
            if not n: raise ValueError("That student has no open loan.")
            return "Marked signed."
        return None

def make_server(host="127.0.0.1", port=8000):
    return ThreadingHTTPServer((host, port), H)

def main():
    p = argparse.ArgumentParser(description="Laptop loans web UI")
    p.add_argument("--host", default="127.0.0.1", help="address to bind (default 127.0.0.1; 0.0.0.0 exposes it to the network)")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--set-password", action="store_true", help="set or reset the login password, then exit")
    a = p.parse_args()
    if a.set_password:
        pw = getpass.getpass("New password: ")
        if len(pw) < MIN_PASSWORD or len(pw) > MAX_PASSWORD: sys.exit(f"Password must be {MIN_PASSWORD}-{MAX_PASSWORD} characters.")
        if pw != getpass.getpass("Confirm: "): sys.exit("Passwords do not match.")
        save_password(pw); print("Password saved to", CONFIG); return
    if a.host not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: listening on %s. There is NO TLS: passwords and student data cross the network in clear text. "
              "Use only on a trusted network." % a.host, file=sys.stderr)
    if not has_password():
        print("No password set yet: open the page from this computer to create one.")
    print(f"Open http://{'127.0.0.1' if a.host == '0.0.0.0' else a.host}:{a.port}")
    make_server(a.host, a.port).serve_forever()

if __name__ == "__main__":
    main()
