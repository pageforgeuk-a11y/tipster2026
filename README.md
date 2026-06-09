# K.H.S.S.C. Tipsters

A weekly football prediction competition, built with Django. Players submit one
entry per game week before a deadline; an organiser enters results; scoring is
automatic; weekly and season leaderboards update on finalise.

This is the Phase 1 build described in [`tipsters-app-spec.md`](./tipsters-app-spec.md).

## What's implemented (Phase 1)

- Email/password accounts; one `Participant` per active season.
- Single-admin organiser tooling via Django admin + a bespoke **results-entry
  screen** (scores, goalscorers, True/False answers, provider auto-fill, override,
  finalise — all in one place).
- Seasons with 40 game weeks, 10 editable fixtures/week, 8 True/False
  questions/week, a per-week manual deadline. Multiple seasons supported.
- Player flow: submit & freely edit before the deadline, locked read-only after;
  own-entry view (players never see others' predictions).
- Full four-section scoring engine (`competition/scoring.py`) — pure, re-runnable,
  exhaustively unit-tested — plus the non-entry "lowest weekly total" default.
- **Canonical player identity for goalscorers** (`competition/players.py`):
  Section 4 matches picks to a `Player` *by id*, not by string, so spelling
  mistakes and same-surname clashes ("which Smith?") don't mis-score. The player
  list self-populates from results, picks use a "Name (Club)" typeahead with a
  free-text fallback, and unmatched/ambiguous picks surface on an admin
  **reconcile** screen. A player who turns out for club *or* country is one
  identity, so international weeks are just a `GameWeek.is_international` toggle —
  no separate table.
- Weekly + season leaderboards with the documented tie-breaks (Section 1).
- Cached `WeeklyScore` / `SeasonScore`, recomputed on finalise (not on read).
- Email reminders via a Vercel Cron endpoint, idempotent per (week, player, window).
- Swappable interfaces: **email** (Resend, with console/SMTP fallback) and
  **results provider** (API-Football, with manual always the source of truth).
- Mobile-first responsive UI.

Phase II items (social login, payments) are deliberately not built; the auth and
provider layers are kept pluggable so they slot in cleanly.

## Quick start (local)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo        # demo season + admin/admin + alice/password123
python manage.py runserver
```

- App: http://localhost:8000 — log in as `alice` / `password123`.
- Admin: http://localhost:8000/admin — log in as `admin` / `admin`.

No environment variables are needed locally: it uses SQLite and prints emails to
the console. Copy `.env.example` to `.env` to override anything.

### Running the tests

```bash
python manage.py test
```

The scoring rules in spec §4 are covered in `competition/tests/test_scoring.py`
(pure rules) and `competition/tests/test_services.py` (recompute, non-entry
default, aggregation, tie-breaks).

## Organiser "Manage" area

There's an on-brand `/manage/` area for organisers (a status dashboard plus the
results-entry and reconcile screens), separate from the raw Django admin.

- **Access** = superuser **or** membership of the **"Organiser" group** (created
  automatically by migration `0005`). Grant access in Django admin → Users → add
  the user to the *Organiser* group. Organisers get the competition tools without
  superuser powers; the Django admin remains for the superuser as a fallback.
- A **"Manage"** link appears in the top nav for anyone with access.

## The organiser's weekly loop

1. **Admin → Seasons:** create a season, tick *is active*.
2. **Admin → Game weeks → Add:** set number, title, date label, **deadline**;
   add the 10 fixtures and 8 True/False questions inline. Save.
3. Select the week in the list → action **"Open selected week(s) to players."**
4. Players submit/edit until the deadline.
5. After matches, click **"Enter results"** on the week (results-entry screen):
   final scores, goalscorers (name + which team they played for), correct
   True/False answers. Optionally **auto-fill** linked fixtures from the
   provider, then override anything. New scorers are added to the player list
   automatically.
6. If any scorer picks couldn't be matched (unknown or ambiguous name), a banner
   links to **Reconcile picks** — map each to the right player in one click.
7. Click **Finalise & rescore** — every entry is (re)scored, the non-entry
   default is applied, and the weekly + season tables update.

Tick **"International week"** on a game week when fixtures are country-vs-country:
scorer labels then show national teams, but identities (and therefore picks)
are unchanged.

## Deployment (Vercel + managed Postgres)

The repo includes `vercel.json` (serverless function + static build + cron) and
`build_files.sh` (installs deps, runs `collectstatic`).

1. **Database.** Create a Postgres database on **Neon** or **Supabase** in the
   **same AWS region** as your Vercel project. Copy its **transaction-mode
   pooler** connection string (Supabase Supavisor `:6543` / Neon pooled), **not**
   the direct connection. The app sets `CONN_MAX_AGE=0` and disables server-side
   prepared statements + cursors automatically — required for transaction poolers.

2. **Email sender (Resend).** Create a Resend API key, and **verify a sending
   domain** in Resend that matches the address in `DEFAULT_FROM_EMAIL`
   (e.g. `tipsters@yourclub.com`). Until the domain is verified, reset/reminder
   emails will be rejected or land in spam. For a first smoke test you can use
   Resend's `onboarding@resend.dev` sender, which only delivers to your own
   Resend account email.

3. **Environment variables** (Vercel → Project → Settings → Environment
   Variables; see `.env.example` for the full list). At minimum:
   - `DATABASE_URL` — the pooler string from step 1.
   - `SECRET_KEY` — a long random value (`python -c "import secrets; print(secrets.token_urlsafe(64))"`).
   - `DEBUG=False`
   - `SITE_URL` — your deployed URL, e.g. `https://tipsters.vercel.app` (used in
     email links).
   - `DEFAULT_FROM_EMAIL` — must match your verified Resend domain (step 2).
   - `RESEND_API_KEY`, and optionally `APIFOOTBALL_API_KEY`.
   - `CRON_SECRET` — a long random value; Vercel Cron sends it as a Bearer token.

4. **Migrate the database** once (the build does *not* run migrations). From your
   machine with the production `DATABASE_URL` exported:
   ```bash
   DATABASE_URL='<pooler-url>' python manage.py migrate
   DATABASE_URL='<pooler-url>' python manage.py createsuperuser
   ```
   Then in the admin: create a Season (tick *is active*), then game weeks.

5. **Deploy.** `vercel --prod` (or connect the Git repo in the Vercel dashboard).
   The `crons` entry in `vercel.json` calls `/cron/send-reminders/` **once a day**
   (08:00 UTC); Vercel sends `Authorization: Bearer $CRON_SECRET`, which the
   endpoint verifies.

   > **Vercel Hobby plan limits cron to once per day**, so the schedule is daily
   > and `REMINDER_WINDOWS_HOURS` defaults to `24` — every deadline gets exactly
   > one reminder in the 24h before it. To remind players closer to the deadline
   > too (e.g. 3h before), either upgrade to Vercel Pro and change the schedule to
   > `0 * * * *`, or trigger `/cron/send-reminders/` hourly from a free external
   > scheduler (e.g. cron-job.org / GitHub Actions) sending the same Bearer token,
   > and set `REMINDER_WINDOWS_HOURS=24,3`.

> Re-run `python manage.py migrate` against the production DB whenever you deploy
> a change that includes a new migration.

## Swapping providers

- **Email** — `competition/emailing.py`. `send_email()` uses Resend when
  `RESEND_API_KEY` is set, otherwise Django's backend (console in dev, SMTP if
  `EMAIL_PROVIDER=smtp`).
- **Results** — `competition/providers/`. Implement `ResultsProvider` and wire it
  into `get_results_provider()`. API-Football is included; manual entry is always
  available and authoritative.

## Assumptions (spec §14 — confirm with the organiser)

These are implemented as the spec's stated defaults; change if the organiser
decides otherwise:

1. **Non-entry default** applies from a player's join week onward.
2. **Season tie-break** is cumulative Section 1 total.
3. **Blank/partial entries** are allowed before the deadline and score 0.
4. **Email/results providers:** Resend + API-Football (both behind interfaces).
5. **Score-derivable True/False** answers: the admin confirms all 8 manually
   (provider auto-fill populates scores/scorers, not T/F, in this build).
6. **Goalscorer identity:** modelled as a canonical `Player` (person), with club
   as a disambiguation label, matched by id. International weeks reuse the same
   identities via the `is_international` flag rather than a separate player list.
