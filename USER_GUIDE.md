# Laptop Loans - User Guide

This program keeps track of which student has which laptop, and creates the
**Student Loan Device Agreement** form (Word and PDF) for each loan.
It runs on your own computer. Nothing is sent over the internet.

## 1. Install (once)

1. Install Python from <https://www.python.org/downloads/>. On the first
   screen, **tick "Add python.exe to PATH"**, then click Install.
2. Open the laptop-loans folder and double-click **setup.bat**. Wait until it
   says "Setup complete" (it needs internet for a minute), then press any key.
3. For PDF forms you need either **LibreOffice** (free,
   <https://www.libreoffice.org/download/>) or **Microsoft Word**. setup.bat
   tells you which one it found. Without either, you still get the Word form.

## 2. Start the program

Double-click **start.bat**. A black window opens and your web browser opens the
Laptop Loans page. **Keep the black window open while you work.** Closing it
stops the program. If the browser does not open, go to
<http://localhost:8000>.

## 3. First run: create a password

The first time, the page asks you to create a password (at least 8 characters).
Choose one and keep it somewhere safe. After that you sign in with it each time.

## 4. Add students and laptops with a CSV file

A CSV file is a spreadsheet saved as "CSV (Comma delimited)". Use the
"Download sample CSV" links on the page to see the right layout.

Students (columns **Name, Student Number, ID/Passport**):

| Name         | Student Number | ID/Passport   |
|--------------|----------------|---------------|
| Amara Okafor | 222012345      | 0501015800087 |
| Thabo Dlamini| 222067890      | 0309125011085 |

Laptops (columns **Asset Tag, Model, Serial Number**):

| Asset Tag | Model          | Serial Number |
|-----------|----------------|---------------|
| LT-001    | Dell Latitude  | ABC123456     |
| LT-002    | Dell Latitude  | ABC123457     |

Choose the file under "Import students from CSV" (or "Import laptops from CSV")
and click **Import**. Anyone already in the system is skipped, so importing the
same file twice is safe. You can also add one student or laptop with the forms
on the page.

## 5. Give a laptop to a student

1. Pick the student and an available laptop and click **Assign**.
2. The program creates the form in the **contracts** folder, as a `.docx`
   and (if LibreOffice or Word is installed) a `.pdf`.

## 6. Find and print the form

Open the **contracts** folder inside the laptop-loans folder, or use the
form link next to the student on the page. Open the PDF and print it. Have the
student sign it.

## 7. Mark the form as signed

Once you have the signed paper, click **Mark signed** next to the student.
The page then shows the form as signed. Keep the paper copy filed safely.

## 8. Return a laptop

When the student brings the laptop back, click **Return** next to their name.
The laptop becomes available for the next student.

## 9. Where the data lives and backups

- **laptops.db** - all students, laptops and loans.
- **contracts** folder - every generated form.
- **config.json** - the password (stored scrambled, not readable).

**To back up:** close the program, then copy **laptops.db** and the
**contracts** folder to a USB drive or a secured network folder. Do this
regularly, for example every Friday. To restore, copy them back into the
laptop-loans folder.

## 10. Updating the form each year

The form template is **Loan_device_Form.docx**. Each year open it in Word,
replace the "2026" wording with the new year, check the other text, and save
it under the same name in the same folder. Forms made after that use the new
wording; old forms are not changed. Do not move or rename the placeholders
and tables in the template.

## 11. Privacy

- This system holds student names, student numbers and ID/passport numbers.
  Treat it as confidential.
- Keep the computer locked and password-protected, and do not share the
  program password.
- **Never upload laptops.db or the contracts folder** to GitHub, email,
  or any public place.
- Delete old records and forms when your policy says you should.

## 12. Troubleshooting

| Problem | What to do |
|---------|-----------|
| "Python was not found" | Install Python from python.org and **tick "Add python.exe to PATH"**. Then run setup.bat again. |
| Black window closes at once | Open the laptop-loans folder, click the address bar, type `cmd`, press Enter, then type `start.bat` to read the message. |
| "Port 8000 in use" / page does not load | The program may already be running in another window, so close it. Or use another port: in the address-bar `cmd` window run `start.bat --port 8001`, then open <http://localhost:8001>. |
| PDF not created | You only got a .docx. Install LibreOffice (free) or Microsoft Word, run setup.bat again, then assign again (or ask your IT contact to regenerate the form). |
| Forgot password | Close the program, delete the file **config.json** in the laptop-loans folder, start again and create a new password. Your data is not lost. |
| Browser shows "can't reach this page" | Check the black window is still open, then reload <http://localhost:8000>. |
