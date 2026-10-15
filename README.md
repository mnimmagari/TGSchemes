# Telangana Farmer Alerts / తెలంగాణ రైతు సమాచారం

A public website that checks official government sources **every day at 10:00 and 18:00 IST**,
reads each new notice in full, and shows farmer-focused key points in **Telugu first, then English**.
AI-written summaries are labelled **"AI సారాంశం · సరిచూడాలి" (AI summary, verify)** and always link to the official notice.

## How it works
1. `.github/workflows/check-alerts.yml` runs on a schedule (04:30 and 12:30 UTC = 10:00 and 18:00 IST).
2. `scripts/collect.py` visits the pages in `scripts/sources.json` (government domains only: `*.gov.in`, `*.nic.in`),
   finds new notice links, downloads and reads them (all PDF pages up to 60), and asks Claude for bilingual key points.
3. Results go into `data/alerts.json`. The workflow commits it and redeploys the site to GitHub Pages.
4. `index.html` shows the notifications, the new-count bell, and the last / next check time.

Scanned (image-only) notices are **not** summarised; they are recorded in `data/seen.json` as `needs-review`.
Passed deadlines are marked expired; alerts older than 90 days move to `data/archive.json` (never deleted).

## One-time setup
1. Create a GitHub repository and push this folder to the `main` branch.
2. **Settings → Secrets and variables → Actions → New repository secret**:
   name `ANTHROPIC_API_KEY`, value = your Claude API key. Never put the key in any file.
3. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
4. **Actions → Check farmer notices → Run workflow** to run the first check now.
5. Open the Pages URL. The status bar turns green after the first successful check.

## Reviewing and correcting alerts
- After checking an AI summary against the official notice, edit `data/alerts.json`
  and change `"review": "auto"` to `"review": "checked"` (the "verify" label disappears).
- To correct a mistake, edit the text in `data/alerts.json` and commit. To withdraw an alert,
  set `"state": "Superseded by a newer notice"` or `"Expired / closed"` rather than deleting it.
- Look for `"needs-review"` entries in `data/seen.json`: these are scanned notices that need a person.

## Adjusting sources
Edit `scripts/sources.json`. Set `"allLinksRelevant": true` for pages that only list farmer notices;
otherwise links are kept only if their text or address mentions farming keywords (English or Telugu).
Use `"enabled": false` to pause a source.

## Costs and limits
- At most 8 new notices are summarised per run (`MAX_NEW_PER_RUN` in the workflow) to cap API cost.
- GitHub may start scheduled runs some minutes late, and pauses schedules in public repos after
  60 days without repository activity; the page shows an amber warning if a check is overdue.

## Tests
`pip install -r requirements.txt reportlab` then `python -m unittest discover -s tests`

## Security notes
- Only `pypdf` is a third-party dependency (pinned; Dependabot opens update PRs weekly).
- TODO: pin GitHub Actions to full commit SHAs, and pip packages with `--require-hashes`.
