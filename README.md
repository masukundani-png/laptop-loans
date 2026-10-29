# Laptop Loans

Track which student has which laptop and generate the signed-ready **Student Loan Device Agreement** (Word + PDF).

## Setup
```
pip install -r requirements.txt
python app.py        # then open http://localhost:8000
```
PDF output uses LibreOffice (if installed) or Microsoft Word (via docx2pdf); otherwise you get the `.docx`.

## Command line
```
python laptops.py add-student "Name" 222012345 --id-number 0501015800087
python laptops.py import-students students.csv     # Name, Student Number, ID/Passport
python laptops.py import-laptops laptops.csv       # Asset Tag, Model, Serial Number
python laptops.py assign 222012345 LT-001          # creates the form in contracts/
python laptops.py list | available | return LT-001 | signed 1
```

The database (`laptops.db`) and generated forms (`contracts/`) contain student data and are git-ignored.
