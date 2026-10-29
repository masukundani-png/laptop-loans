"""Authentication / hardening tests for app.py (stdlib only; server runs on port 0 in a thread)."""
import http.client, os, re, sys, threading, urllib.parse

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import app  # noqa: E402
import laptops  # noqa: E402

PW = "correct horse battery"


class Client:
    def __init__(self, port):
        self.port, self.cookies = port, {}

    def req(self, method, path, data=None, headers=None, raw=None):
        h = dict(headers or {})
        if self.cookies:
            h["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        body = raw
        if data is not None:
            body = urllib.parse.urlencode(data).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=body, headers=h)
        r = conn.getresponse()
        text = r.read()
        for sc in r.msg.get_all("Set-Cookie") or []:
            k, _, rest = sc.partition("=")
            v = rest.split(";")[0]
            if "Max-Age=0" in sc:
                self.cookies.pop(k, None)
            else:
                self.cookies[k] = v
        conn.close()
        return r, text.decode("utf-8", "replace")

    def get(self, path, **kw): return self.req("GET", path, **kw)
    def post(self, path, data=None, **kw): return self.req("POST", path, data=data, **kw)

    def token(self, path):
        """Fetch a form page and return its hidden csrf_token."""
        r, t = self.get(path)
        return re.search(r"name=.csrf_token. value=.([^'\"]+)", t).group(1)

    def setup(self, pw=PW):
        tok = self.token("/setup")
        return self.post("/setup", {"csrf_token": tok, "password": pw, "confirm": pw})

    def login(self, pw=PW):
        tok = self.token("/login")
        return self.post("/login", {"csrf_token": tok, "password": pw})

    def page_csrf(self):
        r, t = self.get("/")
        return re.search(r'name="csrf-token" content="([^"]+)"', t).group(1)


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(laptops, "DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(laptops, "OUT", str(tmp_path / "contracts"))
    monkeypatch.setattr(app, "CONFIG", str(tmp_path / "config.json"))
    monkeypatch.delenv("LAPTOP_LOANS_PASSWORD", raising=False)
    app.reset_state()
    srv = app.make_server("127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown(); srv.server_close()


@pytest.fixture
def cl(server):
    return Client(server.server_address[1])


@pytest.fixture
def authed(cl):
    r, _ = cl.setup()
    assert r.status == 303
    return cl


def test_unauthenticated_redirects(cl):
    # no password yet -> setup; after setup -> login
    r, _ = cl.get("/")
    assert r.status == 303 and r.getheader("Location") == "/setup"
    cl.setup()
    anon = Client(cl.port)
    for path in ("/", "/sample.csv", "/contracts/x.pdf"):
        r, _ = anon.get(path)
        assert r.status == 303 and r.getheader("Location") == "/login", path
    r, _ = anon.post("/add-student", {"name": "a", "student_no": "1"})
    assert r.status == 303 and r.getheader("Location") == "/login"


def test_first_run_setup(cl, tmp_path):
    r, t = cl.get("/setup")
    assert r.status == 200 and "confirm" in t
    tok = cl.token("/setup")
    # too short / mismatch rejected
    r, _ = cl.post("/setup", {"csrf_token": tok, "password": "short", "confirm": "short"})
    assert r.status == 400
    r, _ = cl.post("/setup", {"csrf_token": tok, "password": PW, "confirm": PW + "x"})
    assert r.status == 400
    # missing CSRF rejected
    r, _ = cl.post("/setup", {"password": PW, "confirm": PW})
    assert r.status == 403
    assert not os.path.exists(app.CONFIG)
    r, _ = cl.post("/setup", {"csrf_token": tok, "password": PW, "confirm": PW})
    assert r.status == 303 and app.COOKIE in cl.cookies
    raw = open(app.CONFIG).read()
    assert PW not in raw and "pbkdf2_sha256" in raw
    assert app.load_config()["password"]["iterations"] >= 200_000
    if os.name == "posix":
        assert oct(os.stat(app.CONFIG).st_mode & 0o777) == "0o600"
    r, t = cl.get("/")
    assert r.status == 200 and "Laptop Loans" in t
    # setup is closed once a password exists
    r, _ = Client(cl.port).get("/setup")
    assert r.status == 303 and r.getheader("Location") == "/login"


def test_wrong_and_right_password(authed):
    c = Client(authed.port)
    r, t = c.login("wrong password")
    assert r.status == 401 and "Incorrect" in t and app.COOKIE not in c.cookies
    r, _ = c.get("/")
    assert r.status == 303
    r, _ = c.login(PW)
    assert r.status == 303 and r.getheader("Location") == "/"
    sc = [v for k, v in r.getheaders() if k == "Set-Cookie" and v.startswith(app.COOKIE)][0]
    assert "HttpOnly" in sc and "SameSite=Strict" in sc
    r, _ = c.get("/")
    assert r.status == 200


def test_env_password_override(authed, monkeypatch):
    monkeypatch.setenv("LAPTOP_LOANS_PASSWORD", "from-the-environment")
    c = Client(authed.port)
    assert c.login(PW)[0].status == 401
    assert c.login("from-the-environment")[0].status == 303


def test_lockout(authed):
    c = Client(authed.port)
    for _ in range(app.MAX_FAILS - 1):
        assert c.login("nope nope nope")[0].status == 401
    r, _ = c.login("nope nope nope")
    assert r.status == 429 and r.getheader("Retry-After")
    # even the right password is refused while locked
    r, _ = c.login(PW)
    assert r.status == 429


def test_csrf_rejection(authed):
    tok = authed.page_csrf()
    form = {"name": "Amara", "student_no": "S100"}
    r, _ = authed.post("/add-student", form)
    assert r.status == 403
    r, _ = authed.post("/add-student", {**form, "csrf_token": "forged"})
    assert r.status == 403
    r, _ = authed.post("/import-csv", raw=b"Name,Student Number\nA,1\n")
    assert r.status == 403
    r, t = authed.post("/add-student", {**form, "csrf_token": tok})
    assert r.status == 200 and "Added Amara" in t
    # header token works for the fetch-based CSV import
    r, t = authed.post("/import-csv", raw=b"Name,Student Number,ID/Passport\nBo,S200,1\n",
                       headers={"X-CSRF-Token": tok})
    assert r.status == 200 and "Imported 1 students" in t
    r, t = authed.post("/import-laptops-csv", raw=b"Asset Tag,Model,Serial Number\nLT-1,M,SN1\n",
                       headers={"X-CSRF-Token": tok})
    assert "Imported 1 laptops" in t


def test_security_headers(authed):
    r, t = authed.get("/")
    h = {k.lower(): v for k, v in r.getheaders()}
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "no-referrer"
    assert "no-store" in h["cache-control"]
    csp = h["content-security-policy"]
    nonce = re.search(r"script-src 'nonce-([^']+)'", csp).group(1)
    assert f'<script nonce="{nonce}">' in t and f'<style nonce="{nonce}">' in t
    assert "unsafe-inline" not in csp and "frame-ancestors 'none'" in csp
    r, _ = Client(authed.port).get("/login")
    assert "content-security-policy" in {k.lower() for k, _ in r.getheaders()}


def test_path_traversal_404(authed, tmp_path):
    (tmp_path / "secret.pdf").write_bytes(b"secret")
    os.makedirs(laptops.OUT, exist_ok=True)
    with open(os.path.join(laptops.OUT, "ok.pdf"), "wb") as f:
        f.write(b"%PDF-ok")
    r, body = authed.get("/contracts/ok.pdf")
    assert r.status == 200 and body == "%PDF-ok"
    for p in ("/contracts/../secret.pdf", "/contracts/..%2fsecret.pdf", "/contracts/%2e%2e/secret.pdf",
              "/contracts/..%5csecret.pdf", "/contracts/%2fetc%2fpasswd", "/contracts/missing.pdf",
              "/contracts/ok.txt"):
        r, body = authed.get(p)
        assert r.status == 404 and "secret" not in body, p


def test_logout_invalidates_session(authed):
    old = authed.cookies[app.COOKIE]
    tok = authed.page_csrf()
    r, _ = authed.post("/logout", {})            # no CSRF token
    assert r.status == 403
    r, _ = authed.post("/logout", {"csrf_token": tok})
    assert r.status == 303 and r.getheader("Location") == "/login"
    stale = Client(authed.port)
    stale.cookies[app.COOKIE] = old               # replay the old cookie
    r, _ = stale.get("/")
    assert r.status == 303 and r.getheader("Location") == "/login"


def test_body_size_cap(authed):
    tok = authed.page_csrf()
    # declare an oversized body; the server must refuse on the header alone
    r, _ = authed.post("/import-csv", raw=b"x", headers={"X-CSRF-Token": tok, "Content-Length": str(app.MAX_BODY + 1)})
    assert r.status == 413


def test_unsafe_ids_rejected_and_escaped(authed):
    tok = authed.page_csrf()
    r, t = authed.post("/add-student", {"csrf_token": tok, "name": "<script>x</script>", "student_no": "../evil"})
    assert "letters, digits" in t
    r, t = authed.post("/add-laptop", {"csrf_token": tok, "tag": "a/b", "serial": "s"})
    assert "letters, digits" in t
    r, t = authed.post("/import-csv", raw=b"Name,Student Number\nA,..\\x\n", headers={"X-CSRF-Token": tok})
    assert "Nothing imported" in t
    r, t = authed.post("/add-student", {"csrf_token": tok, "name": "<b>Bob</b>", "student_no": "S1"})
    assert "<b>Bob</b>" not in t and "&lt;b&gt;Bob&lt;/b&gt;" in t


def test_assign_return_signed(authed, monkeypatch):
    monkeypatch.setattr(laptops, "make_contract", lambda aid: None)
    tok = authed.page_csrf()
    authed.post("/add-student", {"csrf_token": tok, "name": "Amara", "student_no": "S1"})
    authed.post("/add-laptop", {"csrf_token": tok, "tag": "LT-1", "serial": "SN"})
    r, t = authed.post("/assign", {"csrf_token": tok, "student_no": "S1", "tag": "LT-1"})
    assert "Assigned LT-1" in t and "action='/return'" in t and "Mark signed" in t
    r, t = authed.post("/signed", {"csrf_token": tok, "student_no": "S1"})
    assert "Marked signed" in t and "Mark signed</button>" not in t
    r, t = authed.post("/return", {"csrf_token": tok, "tag": "LT-1"})
    assert "Returned LT-1" in t and "action='/return'" not in t
    r, t = authed.post("/return", {"csrf_token": tok, "tag": "LT-1"})
    assert "not currently assigned" in t
