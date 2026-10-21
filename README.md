# White Petals Resort — Local Business Development CRM

A local-first Flask application for maintaining corporate prospect records, checking public company websites, tracking sales stages and follow-ups, preparing editable outreach drafts, and reporting confirmed bookings separately from estimated opportunities.

This project grows the existing OpenStreetMap lead collector and its SQLite database. The dashboard uses the existing `white_petals_sales.db` file and applies additive schema migrations at startup; it does not erase the current company records.

## 1. Install on Windows

Open PowerShell and run:

```powershell
cd "C:\Users\sonur\OneDrive\Desktop\WhitepetalsAI"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

If PowerShell blocks environment activation, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or invoke the environment's interpreter directly as `.\.venv\Scripts\python.exe`.

Edit `.env` and set a unique `APP_PASSWORD` and a strong, random `SECRET_KEY`. For example, generate a key with:

```powershell
```

Copy the printed value intpython -c "import secrets; print(secrets.token_urlsafe(48))"
o `.env`. Do not share or commit `.env`.

Start the application:

```powershell
python app.py
```

Open <http://127.0.0.1:5000>. Keep the PowerShell window open while using the application. Stop it with Ctrl+C.

## 2. What works

- Existing SQLite company data, additive database setup, lead score, deduplication by company, city, and state, search, filters, pagination, lead editing and confirmed-delete workflow.
- Company category classification in the lead form, CRM table, and pipeline, with category filters and CSV/Excel import/export. Existing records are categorized conservatively from their saved industry and company name where possible; uncertain records remain `Other`.
- Manual lead entry plus CSV and `.xlsx` import (5 MB and 5,000 row limits), CSV/XLSX export, and an import template.
- Optional public listing search from the **Find new leads** dashboard panel using OpenStreetMap across technology/IT, company offices, event management, corporate travel, consulting/training, industrial/manufacturing, banking/finance, insurance, educational institutions, professional organizations, event venues, and retail. New company-and-city matches are added to the CRM. Existing matches are counted and only missing public details are filled; manual values and pipeline status are preserved. Categories match map tags and are discovery hints, not verified company industries or buying signals. Records remain unverified; the source record URL is retained when provided.
- Lead search accepts up to five comma-separated city, district, or state names, for example `Bengaluru, Mysuru` or `Karnataka, Tamil Nadu`. Each area is searched separately with a pause between requests, so results without address tags retain the individual searched city or state instead of storing the combined search phrase as a city. Bangalore/Bengaluru and Mysore/Mysuru are aliases. State searches may return many records and may take longer or be rate-limited.
- Collector CSVs include a transparent 0–4 data-completeness indicator and a suggested human review step based on source URL, website, public contact information, and city/state fields. This is a data-quality aid, not an AI-generated buyer score or permission to contact. Temporary Overpass errors are retried with bounded delays, and CLI output files are replaced atomically after successful export.
- The original command-line collector also accepts locations: `python main.py --city "Bengaluru, Mysuru" --category technology --category bank`.
- The standalone CSV collector accepts the same location and category options: `python new_company_database.py --city "Mysuru, Karnataka" --category technology --output mysuru_leads.csv`. Research queue searches use each lead's saved city and state instead of assuming Bengaluru.
- State is stored separately from city throughout manual entry, discovery, import/export, and lead filters. Existing Bengaluru/Mysuru records receive a conservative Karnataka state backfill during the additive migration.
- User-triggered public website checks for a supplied public URL, with size/time limits, robots.txt checks (fail closed when permission cannot be verified), public-address checks, and no bypass of site restrictions. Research failures are marked incomplete. Verify findings and terms before outreach.
- Follow-up reminders, notes/activity history, a sales pipeline, and reports that separate estimated opportunity from revenue entered for a confirmed booking.
- Contact permission is tracked separately as **Not recorded**, **Permission recorded**, or **Opted out**, with permission source and date. Existing/imported contacts default to Not recorded; they are not presumed to have permission. An Opted out record is forced to **Do Not Contact** and cannot be reopened without recording renewed permission, its source, and date. This is a recordkeeping safeguard, not a legal determination.
- **Database backups:** the Setup page can create and download a consistent SQLite snapshot, and restore a CRM backup after a typed confirmation. Restore first saves the current database as a safety backup and validates the selected SQLite file. The app also creates a daily local snapshot at the configured time while it is running. Backups contain sensitive CRM data; the `backups` folder is git-ignored. Keep an additional copy in a secure, separate location.
- The business-development dashboard summarizes active estimated pipeline value separately from confirmed booking revenue, highlights leads still needing research, and links stage counts directly to the filtered pipeline. Open estimates exclude confirmed, lost, and do-not-contact records.
- Editable email/WhatsApp drafts can use deterministic templates or an explicitly selected Gemini API draft mode. Only the company name, category, industry, city/state, sales stage, requested purpose, and configured resort facts are sent for AI drafting; contact details and CRM notes are excluded. Review AI output and verify claims. No draft is automatically sent.
- The **AI Agent Control Room** includes specialist business-development agents, a persistent work log, and custom agent profiles. Assign a task to run an on-demand Gemini analysis; outcomes and failures are recorded. Agents prepare plans, checklists, priorities, and draft material only—they do not browse, alter CRM data, send messages, or confirm bookings. Tasks send the profile, assignment, and up to 25 limited active-lead summaries to Gemini; contact details, notes, website content, and communication history are excluded. Custom guidance and task text are also sent, so never put secrets or personal data there. Review all output.
- The built-in **AI Call Coach** prepares permission-first call guides, call-note checklists, and clearly labeled fictional practice role-plays. For a real lead, it requires recorded contact permission, its source, and date, and shares only that lead's limited business summary with Gemini. Fictional practice sends no CRM lead data. It cannot place, record, listen to, or contact people; live phone-service integration is not configured. Obtain any required consent, verify resort facts, and make calls yourself.
- Quick AI tools remain available for daily plans, lead prioritization, and single-lead strategy. AI responses are suggestions only and are not a substitute for verified resort information, permission, or human approval.
- **Event Experience Studio** creates a reviewable event concept, experience ideas, draft agenda, planning checklist, and prospect discovery questions from an active lead and the stated event goal. Gemini receives limited company/business context plus the event details; contact details, CRM notes, website content, and communication history are excluded. Only non-empty resort facts configured in `resort_info.json` are passed as business-supplied facts; the current file has blank commercial details. The output is not saved or sent and is not a quote, availability check, or booking. Confirm resort facilities, capacity, prices, taxes, meals, availability, and terms directly before sharing.
- A daily scheduled CRM metrics report while `app.py` is running. The schedule defaults to 18:00 Asia/Kolkata and is configurable in `.env`.
- Health endpoint: <http://127.0.0.1:5000/health>.
- Optional local password login and CSRF protection for form actions.

The existing CSV files are not overwritten by imports. The OpenStreetMap collection action writes its fresh results to `corporate_leads.csv`, matching the previous app's behavior.

## 3. Sample use

1. Visit **Overview & Leads** and import `sample_leads.csv`, or add a lead manually. Choose a company category separately from the source industry/category; uncertain records can stay `Other`.
2. Open a lead to set its status, source, next follow-up, estimated opportunity, and (only after confirmation) revenue.
3. Use **Company Research** only for a company's official public website. Research is user-triggered.
4. Create a standard template or opt-in Gemini email/WhatsApp draft in **Sales Assistant**, review it in **Drafts**, and copy it into an authorized channel.
5. Use **AI business development** to assign work to a specialist or create a custom agent. Each task runs only when submitted, and its result/failure appears in the persistent work log. Treat output as unverified suggestions.
6. Use **Follow-ups** to complete/reschedule reminders and **Reports** to review current totals or save a daily report.

## 4. Schedule the app on Windows

The built-in scheduler runs only while the app process is running. To keep it available after signing in:

1. Open **Task Scheduler** → **Create Basic Task**.
2. Choose **When I log on**.
3. Set the action to **Start a program**.
4. Program: the full path to `.venv\Scripts\python.exe`.
5. Arguments: `app.py`.
6. Start in: `C:\Users\sonur\OneDrive\Desktop\WhitepetalsAI`.

Set `DAILY_REPORT_HOUR` (0–23) and `DAILY_REPORT_MINUTE` (0–59) in `.env` for the Asia/Kolkata report time. Daily database backups default to 02:15 Asia/Kolkata and can be adjusted with `DAILY_BACKUP_HOUR` and `DAILY_BACKUP_MINUTE`. A sleep/off computer or stopped app means scheduled work will not run. AI agents are run on demand; they are not scheduled or autonomous. The app does not discover new companies, run unattended website research, or send messages in the background.

## 5. External services and known limits

- **OpenStreetMap Overpass:** public listing search requires an internet connection and may be rate-limited or unavailable. It does not find every company or verify buyers.
- **Google Gemini:** optional, user-initiated draft generation and agent-task runs. Set `GEMINI_API_KEY` in your private, git-ignored `.env` file and restart the app; optionally set `GEMINI_MODEL` (defaults to `gemini-3.8-flash`). Check Google AI Studio for the model IDs available to your account. Keep the key out of chat, source code, logs, and screenshots. Requests may incur provider charges and send the limited prospect/resort fields described above to Google. Standard templates work without an API key.
- **Gmail:** OAuth, sending, reply processing, and delivery status are not implemented.
- **WhatsApp:** official Business Platform integration, message sending, inbound replies, and provider status are not implemented.
- **Commercial resort details:** add only verified facts to `resort_info.json`. Blank details are not invented; confirm prices, taxes, packages, amenities, availability, capacity, and terms before customer-facing use.
- **Security/deployment:** this is intended for local use and binds to `127.0.0.1` by default. Before network/cloud deployment, require a password and persistent secret, use HTTPS, configure production-grade authentication/authorization, backups, firewalling, and deployment monitoring. Do not expose the development server directly to the internet.
- **Data protection:** this app does not automatically send messages. You are responsible for lawful data collection, retention, contact permissions, opt-outs, and compliance with relevant website and messaging rules.

## 6. Backups and restore

Use **Setup → Create & download database backup** for a consistent live snapshot; the app also saves one daily when the scheduler is running. Copies remain in the git-ignored `backups` folder. For recovery, choose a saved CRM snapshot in Setup and type `RESTORE`. The current database is first backed up as a safety copy. Restore accepts only a structurally valid backup from this CRM. Store another copy securely outside this computer; database files contain prospect/customer information. Back up `.env` separately through a secure method if needed—it is not included in database snapshots.

## 7. Tests

Run the automated tests from the project directory:

```powershell
python -m unittest discover -s tests -v
```

Tests use a temporary database and do not modify the main company records.
