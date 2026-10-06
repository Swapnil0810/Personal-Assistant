# Finance Tracker (Streamlit + Gemini Flash)

Pages: Dashboard (KPIs, alerts, quick add, AI advice) · Bot (add/edit/delete/query in plain English) · Analytics (date range, categories, compare vs previous period/week/month/year/custom) · Ledger (Excel-like editable grid, filters, Excel export) · Settings (budgets/targets, import, backup).

## Run locally
```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # fill GEMINI_API_KEY, APP_PASSWORD
streamlit run app.py
```
Free Gemini key: https://aistudio.google.com (Get API key). Data is stored in `./data/finance.db` (SQLite) unless `DATABASE_URL` is set.

## Free deployment (recommended)
1. **Database**: create a free Postgres on Neon or Supabase, copy the connection string (use the pooled one) into `DATABASE_URL`. Free hosts wipe local disk on restart, so SQLite will not survive there.
2. **Host**: push this folder to GitHub (secrets are git-ignored), then deploy on https://share.streamlit.io, main file `app.py`.
3. **Secrets** (App settings → Secrets): `GEMINI_API_KEY`, `APP_PASSWORD`, `DATABASE_URL`, optional `GEMINI_MODEL`, `APP_TIMEZONE`.

The app URL is public, so always set `APP_PASSWORD`.

## Notes
- Bot models: `GEMINI_MODEL` first (optional), then the newest Flash models your key can use, discovered from the API (refreshed hourly), then Flash-Lite. If discovery fails it falls back to a built-in list. Models that 404, hit 429 or return 503 are skipped.
- Each bot message can use several Gemini requests (one per tool call); free-tier limits are per minute and per day.
- Alerts compare month-to-date with the same days of last month.

## Logs
Everything goes to `logs/app.log` (rotating, 1 MB x 3, local timezone) and to the console: every bot prompt and reply, each tool call with arguments and result, Gemini errors per model (code, status, message), the models discovered from the API, database errors with full tracebacks, and unhandled page errors. Open **Settings → Logs** to read or download it. Change the folder with the `LOG_DIR` secret. On Streamlit Community Cloud the file is wiped on restart; use *Manage app → Logs* there for the console copy.
