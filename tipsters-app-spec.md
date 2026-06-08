# K.H.S.S.C. Tipsters — Web App Specification

> Build spec for Claude Code. This document is the source of truth for the
> football (soccer) tipping competition app. Implement Phase 1 fully; Phase II
> items are noted but **not** to be built yet (design so they slot in cleanly).

---

## 1. Overview

The K.H.S.S.C. Tipsters is a weekly football prediction competition currently
run on paper/email. Each week an organiser publishes a form of 10 fixtures plus
bonus sections; players predict outcomes and email entries before a deadline;
the organiser scores everything by hand and tracks a season-long table.

This app digitises the whole loop: an **admin** configures each game week and
enters results; **players** register, submit/edit predictions before a per-week
deadline, and view leaderboards. Scoring is automatic.

- **Season length:** 40 game weeks.
- **Players:** ~50 at launch; **architect for thousands** (see §11).
- **Prizes:** a weekly prize and season-long prizes (the app identifies winners
  and displays standings; money/payouts are handled offline in Phase 1).

---

## 2. Tech stack & deployment

- **Framework:** Django (latest stable) + Django admin for the organiser tooling.
- **Database:** PostgreSQL via an external managed provider (Neon or Supabase
  free tier). Connection via `psycopg` (use the binary package on Vercel).
- **DB connection handling (serverless):** co-locate the database region with the
  Vercel deployment region (same AWS region) to keep latency in single-digit ms.
  Point `DATABASE_URL` at the provider's **transaction-mode pooler endpoint**
  (Supabase Supavisor `:6543` / Neon pooled endpoint), **not** the direct
  connection. Set Django `CONN_MAX_AGE = 0` (don't hold connections across
  suspended invocations) and **disable server-side prepared statements** in
  psycopg (transaction-mode poolers don't support them). This keeps the DB's
  connection count bounded regardless of how many function instances Vercel spins
  up.
- **Hosting:** Vercel (zero-config Django support, Fluid compute). Static files
  served by Vercel's CDN (Django `collectstatic`).
- **Scheduled jobs:** Vercel Cron for email reminders (see §9). Do **not** rely
  on always-on background workers — none exist on serverless.
- **Frontend:** Server-rendered Django templates, responsive and **mobile-first**
  (most players are on phones). No SPA required for Phase 1.
- **Email:** transactional email provider (e.g. Resend, Postmark, or SMTP) for
  reminders and account email. Keep behind a small interface so it's swappable.
- **Constraint:** keep the deployed function bundle under Vercel's 250 MB
  unzipped limit.

---

## 3. Roles

- **Admin (organiser, e.g. Neil):** creates seasons and game weeks, sets the 10
  fixtures, the deadline, the 8 True/False questions; enters/imports results;
  reviews auto-filled data; can override anything; views all entries.
- **Player (participant):** registers an account, submits and edits one entry
  per game week before the deadline, views their own entry and the leaderboards.

Use Django's auth. Admin = `is_staff`/`is_superuser`. Players are regular users
with a linked `Participant` profile.

**Phase 1 auth:** email + password accounts created on the site.
**Phase II:** social logins (Google/Apple). Keep the auth layer pluggable.

---

## 4. Core scoring rules (implement exactly)

Each game week has **four sections**. A player's **weekly total** = S1 + S2 + S3 + S4.

### Section 1 — Match result & exact score (10 fixtures)
For each fixture the player predicts `home_score` and `away_score` (non-negative
integers). Points per fixture:

**Outcome points** (correct Win/Draw/Win prediction):
- Predicted home win **and** actual home win → **3 pts**
- Predicted draw **and** actual draw → **4 pts**
- Predicted away win **and** actual away win → **5 pts**
- Otherwise → 0

**Exact-score bonus** (predicted scoreline equals actual scoreline exactly):
- Actual **combined** goals (home + away) ≤ 4 → **+5 pts**
- Actual **combined** goals ≥ 5 → **+7 pts**

Outcome points and the exact-score bonus **stack** (an exact score also satisfies
the outcome). Example: predict 1–2, actual 1–2 → away win 5 + bonus 5 = **10 pts**.
Example: predict 3–3, actual 3–3 → draw 4 + bonus 7 = **11 pts**.

`Section1 total = sum over all 10 fixtures.`

### Section 2 — Total goals across all 10 matches
Player predicts one integer = total goals in all 10 fixtures combined.
Let `diff = abs(predicted_total - actual_total)`:
- diff 0 → **5 pts**
- diff 1 → **3 pts**
- diff 2 → **2 pts**
- diff 3 → **1 pt**
- diff ≥ 4 → 0

### Section 3 — True/False (8 bespoke questions)
The 8 questions are written fresh by the admin each week (e.g. "At least one
penalty is scored", "A substitute scores", "Two or more draws"). Player answers
True/False for each.
- **+2 pts** per correct answer
- **+4 pt bonus** if all 8 are correct
- Max 20.

The correct answers are set by the admin (see §7) — many require match detail no
score feed provides.

### Section 4 — Predict the scorers (4 ranked picks)
Player enters up to 4 player names, ranked top→bottom. Position value:
- Pick 1 → **4 pts**, Pick 2 → **3 pts**, Pick 3 → **2 pts**, Pick 4 → **1 pt**

For each pick, if that player scored **at least one** goal in any of the week's
10 fixtures, award the position points. Plus **+1 pt for each additional goal**
that player scored beyond the first.
Example: the 4-point pick scores a hat-trick → 4 + (3−1) = **6 pts**.

Scorer matching needs actual goalscorer data (player + goal count) from the
results feed where available, else manual admin entry. Matching should be
case-insensitive and tolerant; admin can confirm/correct matches.

### Weekly & season aggregation
- **Weekly total** = S1 + S2 + S3 + S4.
- **Non-entry rule:** a participant who does **not** submit in a given week is
  assigned that week's **lowest submitted weekly total**. This applies only from
  the participant's **join week onward** (weeks before they joined are not
  counted for them). *(Assumption — confirm with organiser.)*
- **Season total** = sum of weekly totals across all game weeks in the season.

### Tie-breaks
- **Weekly leaderboard:** highest **Section 1** total that week; if still tied,
  joint position.
- **Season leaderboard:** highest **cumulative Section 1** total across the
  season; if still tied, joint position. *(Assumption — confirm.)*

---

## 5. Data model (suggested)

Use a normalised schema. Store predictions and results separately so re-scoring
is deterministic and re-runnable.

- **Season**: `name`, `start_date`, `is_active`. Supports **multiple seasons**
  (archive one, start the next 40-week season).
- **Participant**: 1:1 with `User`; `display_name`, `season` (or M2M
  membership), `join_week` / `joined_at`.
- **GameWeek**: `season` FK, `week_number` (1–40), `title`, `date_range_label`,
  `deadline` (timezone-aware datetime, set per week), `status`
  (draft / open / locked / results_in / finalised).
- **Fixture**: `game_week` FK, `order` (1–10), `home_team`, `away_team`,
  `kickoff` (datetime, optional), `external_match_id` (nullable, for feed),
  `actual_home_score`, `actual_away_score` (nullable until results entered).
- **TrueFalseQuestion**: `game_week` FK, `order` (1–8), `text`,
  `correct_answer` (nullable boolean until results entered).
- **FixtureGoal** (for scorer scoring): `fixture` FK, `player_name`,
  `goals` count (or one row per goal), `is_penalty`, `minute` (optional).
- **Entry**: `participant` FK, `game_week` FK, `submitted_at`, `is_locked`,
  unique together (participant, game_week). One entry per player per week.
- **MatchPrediction**: `entry` FK, `fixture` FK, `pred_home`, `pred_away`.
- **TotalGoalsPrediction**: `entry` FK, `predicted_total`.
- **TrueFalseAnswer**: `entry` FK, `question` FK, `answer` boolean.
- **ScorerPick**: `entry` FK, `position` (1–4), `player_name`.
- **WeeklyScore** (computed/cached): `participant`, `game_week`, `s1`, `s2`,
  `s3`, `s4`, `total`, `is_non_entry_default` flag.
- **SeasonScore** (computed/cached): `participant`, `season`, `total`.

Scoring should be a pure, re-runnable function: given results + an entry,
produce the four section scores. Cache results in `WeeklyScore`/`SeasonScore`
and recompute on results change.

---

## 6. Player workflow

1. **Register** (email + password) → creates `User` + `Participant`, joined to
   the active season at the current week.
2. **Log in.**
3. **View open game week**: the 10 fixtures, the total-goals input, the 8 T/F
   questions, and 4 scorer-pick slots, plus the deadline countdown.
4. **Submit entry**; **edit freely any time before the deadline**. After the
   deadline the entry is locked and read-only.
5. **View own entry** for any week (only their own — players never see others'
   predictions).
6. **View leaderboards**: current week and season-to-date, with their own
   position highlighted.

Validation: scores are non-negative integers; all 10 fixtures, total-goals, all
8 T/F, and scorer slots should be completable but partial saves allowed before
deadline (decide a sensible default — e.g. blanks score 0).

---

## 7. Admin workflow (per game week)

1. **Create game week** under the active season: number, title, date label,
   **deadline** (set manually each week — default ~1 hour before first kickoff;
   may be Fri/Sat/other).
2. **Set the 10 fixtures**: home/away teams, optional kickoff times. Usually the
   10 Premier League games, but may include lower-league, international, or cup
   fixtures — so fixtures are **fully free-text/editable, never locked to a PL
   feed**. Optionally link a fixture to an `external_match_id` for auto-results.
3. **Write the 8 True/False questions.**
4. **Open** the week to players.
5. After matches, **enter results**:
   - Final scores per fixture, goalscorers (with goal counts/penalty flags),
     and the correct True/False answers.
   - **Auto-fill via results provider** (§8) where a fixture is linked; admin
     **reviews and can override every field**. Manual entry is always available
     and is the source of truth.
   - The app may pre-suggest answers for score-derivable T/F questions (e.g.
     "more goals by home teams than away"), but the admin confirms all 8.
6. **Finalise** → triggers (re)scoring of all entries, applies the non-entry
   lowest-score default, updates weekly + season tables, and identifies the
   weekly winner.

The Django admin should cover most of this; build a custom **results-entry
screen** for step 5 (score + goalscorers + T/F + provider auto-fill + override
in one place), since the stock admin is clumsy for that.

---

## 8. Results data provider (cheap, swappable)

- Define a `ResultsProvider` interface: given a fixture / `external_match_id`,
  return final score, goalscorers (name + count, penalty flag), and optionally
  enough detail to *suggest* T/F answers.
- **Default to a free tier** (e.g. API-Football free tier, ~100 req/day — ample
  for ~10 matches/week; or football-data.org). Keep the API key in env vars.
- **Always allow manual entry and override.** The feed is a convenience, not a
  dependency: lower-league/international/cup fixtures and the bespoke T/F
  questions will often be entered by hand.
- Goalscorer name matching to scorer picks: fuzzy/case-insensitive with admin
  confirmation.

---

## 9. Deadlines, locking & reminders

- **Locking** is enforced at submission time: reject/disable edits when
  `now >= game_week.deadline`. No background job needed for locking.
- **Email reminders** via **Vercel Cron**: a scheduled endpoint runs (e.g.
  hourly) and emails players who haven't submitted for the current open week as
  the deadline approaches (e.g. a reminder N hours before). Make the reminder
  windows configurable; ensure idempotency (don't double-send).
- All datetimes timezone-aware; display in UK time.

---

## 10. Leaderboards

- **Weekly**: rank by weekly total desc, tie-break = Section 1 total.
- **Season**: rank by cumulative total desc, tie-break = cumulative Section 1.
- Show the four section subtotals on the weekly view.
- A player sees standings but **not** others' individual predictions.
- After a week is finalised, the non-entry default is reflected in both tables.

---

## 11. Scaling considerations (now ~50, design for thousands)

- Avoid per-request N+1s; cache `WeeklyScore`/`SeasonScore` rather than
  recomputing leaderboards on every page load.
- Recompute scores on results change (admin finalise), not on read.
- Index `Entry(participant, game_week)`, `WeeklyScore(game_week, total)`,
  `SeasonScore(season, total)`.
- Paginate leaderboards.
- Keep scoring logic pure and testable so a batch rescore over thousands of
  entries is fast and safe.
- Be mindful of Vercel function cold starts and execution limits; keep
  finalise/rescore efficient (bulk queries, `bulk_create`/`bulk_update`).

---

## 12. Phasing

**Phase 1 (build now):**
- Email/password accounts, single-admin organiser tooling.
- Season + 40 game weeks, 10 editable fixtures/week, 8 T/F questions/week,
  per-week manual deadline.
- Player entry submit/edit-before-deadline, own-entry view.
- Full four-section scoring, non-entry rule, weekly + season leaderboards,
  tie-breaks.
- Results: manual entry + optional free-tier provider auto-fill with override.
- Email reminders via Vercel Cron.
- Multiple seasons.
- Mobile-first responsive UI.

**Phase II (design for, do not build):**
- Social logins (Google/Apple).
- Payment / "money behind the bar" tracking (entry fees, who owes what).
- Scale-out features as player counts grow.

---

## 13. Non-functional requirements

- **Mobile-first** responsive design; usable one-handed on a phone.
- **Security:** Django auth best practices, CSRF, secrets in env vars, no
  predictions leaked between players, deadline enforced server-side.
- **Testing:** unit tests for the scoring function covering every rule in §4,
  including the stacking bonus, the 0–4 vs 5+ split, all-correct T/F bonus,
  multi-goal scorer picks, and the non-entry default.
- **Data integrity:** results changes recompute scores deterministically; one
  entry per player per week (DB constraint).

---

## 14. Open items to confirm with the organiser

1. Non-entry default applies from join week onward (assumed) — confirm.
2. Season tie-break = cumulative Section 1 (assumed) — confirm.
3. Handling of partial/blank entries submitted before deadline (assumed: blanks
   score 0).
4. Preferred email provider and results API provider (and any budget).
5. Whether score-derivable T/F questions should be auto-suggested or always
   fully manual.
