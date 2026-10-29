# Laptop Loans

Small laptop-loan tracker for a university IT/CAT office. It records which
student holds which laptop and generates a filled **Student Loan Device
Agreement** as `.docx` and `.pdf`. Pure Python standard library plus
`python-docx`; data is stored in SQLite.

Non-technical staff: see [USER_GUIDE.md](USER_GUIDE.md).

## Quick start

Windows:

1. Install Python 3 from python.org (tick "Add python.exe to PATH").
2. Double-click `setup.bat` (creates `.venv`, installs requirements).
3. Double-click `start.bat` (starts the server and opens http://localhost:8000).

Linux / macOS:

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python app.py              # http://localhost:8000
python app.py --host 127.0.0.1 --port 8001
```

PDF output: LibreOffice (`soffice`) if installed, else Microsoft Word via
`docx2pdf` (Windows), else only the `.docx` is produced.

## Features

- Web UI: add students/laptops, assign, return, mark form signed.
- CSV import: students (`Name, Student Number, ID/Passport`) and laptops
  (`Asset Tag, Model, Serial Number`); duplicates are skipped; sample CSVs
  downloadable from the UI.
- Contract generation from `Loan_device_Form.docx` into `contracts/`.
- Password login: first run asks for a password (min 8 characters), stored
  hashed in `config.json`. `LAPTOP_LOANS_PASSWORD` env var overrides it.
- Return and Mark-signed buttons next to each assigned student.
- Command line for scripting (below).

## CLI

```
python laptops.py add-student "Name" 222012345 --id-number 0501015800087 [--grade G --guardian N --guardian-email E]
python laptops.py add-laptop LT-001 --model "Model" --serial SN [--value 0]
python laptops.py import-students students.csv
python laptops.py import-laptops laptops.csv
python laptops.py assign 222012345 LT-001 [--date YYYY-MM-DD]   # creates the form
python laptops.py return LT-001 [--date YYYY-MM-DD]
python laptops.py signed 1 [--date YYYY-MM-DD]                  # assignment id
python laptops.py list [--all] | available
python laptops.py contract 1                                    # regenerate form
```

## Project layout

```
app.py                 web UI / HTTP server (stdlib http.server)
laptops.py             database, CLI, CSV import, contract generation
Loan_device_Form.docx  form template (update the year annually)
requirements.txt       runtime deps (python-docx; docx2pdf on Windows)
requirements-dev.txt   test deps (pytest)
setup.bat / start.bat  Windows installer and launcher
USER_GUIDE.md          guide for office staff
tests/                 pytest suite
laptops.db             SQLite data (git-ignored, created on first run)
contracts/             generated forms (git-ignored)
config.json            hashed password (git-ignored)
```

## Tests

```
pip install -r requirements-dev.txt
python -m pytest
```

## Security notes

- The server binds to `127.0.0.1` by default so it is reachable only from the
  same machine. Use `--host 0.0.0.0` only on a trusted network, and note there
  is no TLS.
- Passwords are stored hashed in `config.json`; resetting means deleting that
  file (anyone with file access can do this).
- `laptops.db` and `contracts/` hold personal data (names, student numbers,
  ID/passport numbers). Never commit them; keep `.gitignore` entries for
  `laptops.db`, `contracts/`, `config.json`, `.venv/`.
- Restrict access to the PC and back up `laptops.db` + `contracts/` securely.

## Limitations

- Single-office, single-machine tool; no multi-user accounts or audit log.
- No HTTPS; not meant to be exposed to the internet.
- PDF needs LibreOffice or Word; otherwise only `.docx`.
- The template placeholders in `Loan_device_Form.docx` must stay intact.
- `start.bat` opens port 8000 in the browser; if you pass `--port`, open the
  new address manually.
