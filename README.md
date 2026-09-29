# DeadlineSOS

DeadlineSOS is a Flask + SQLite academic workload manager for turning deadlines into a clear next action.

It includes student registration and login, profile-based study availability, task add/edit/delete/complete flows, workload and deadline risk scoring, a recommended study order, and progress analytics. Existing databases are migrated automatically with a per-task owner column.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 and create a student account. The SQLite database is created as `deadlinesos.db` on first run.

## Real email OTP

Registration sends OTPs through SMTP. Set these environment variables before starting the app:

```powershell
$env:SMTP_HOST = "smtp.gmail.com"
$env:SMTP_PORT = "587"
$env:SMTP_USERNAME = "your-email@gmail.com"
$env:SMTP_PASSWORD = "your-gmail-app-password"
$env:SMTP_FROM = "your-email@gmail.com"
python app.py
```

For Gmail, use an App Password rather than your normal account password. Do not commit these values to the project.

## ChatGPT-style AI Coach

Set an OpenAI-compatible API key to enable natural-language answers:

```powershell
$env:AI_API_KEY = "your-api-key"
$env:AI_MODEL = "gpt-4o-mini"
python app.py
```

The optional `AI_API_URL` variable can point to another OpenAI-compatible provider. Without a key, the app uses its local planning fallback.

## Test

```powershell
pytest
```
