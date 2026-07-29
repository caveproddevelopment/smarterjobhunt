# SmarterJobHunt — Backend

Flask API on top of PostgreSQL, using raw SQL (psycopg2) — no ORM. This has been
built and tested end-to-end (schema applied, seed data loaded, every endpoint
exercised with curl) so it's ready to point the frontend at.

## Stack

- **PostgreSQL** — schema in `db/schema.sql`
- **Flask** — thin route layer, no ORM; every query is plain parameterized SQL
- **Auth** — email/password, signed bearer tokens via `itsdangerous` (no session
  cookies, so it works cleanly across origins/ports in local dev and once the
  frontend and backend are deployed separately, e.g. Vercel + Railway)

## 1. Create the database

```bash
# as the postgres superuser (adjust for your setup)
psql -c "CREATE USER smarterjobhunt WITH PASSWORD 'devpassword' CREATEDB;"
psql -c "CREATE DATABASE smarterjobhunt OWNER smarterjobhunt;"
```

On Railway, add a PostgreSQL plugin instead and copy the connection string it
gives you into `DATABASE_URL` below — skip the two commands above.

## 2. Set up the Python environment

```bash
python3 -m venv venv
source venv/bin/activate        # venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env            # then edit DATABASE_URL / SECRET_KEY if needed
```

## 3. Load the schema and sample data

```bash
psql -d smarterjobhunt -f db/schema.sql
psql -d smarterjobhunt -f db/seed.sql
```

`db/seed.sql` inserts the same four companies/jobs the frontend's mock data
uses (Northlane Robotics, Fielded, Harborline, Kestrel Health) plus a demo
login and the three saved searches from the wireframe, so the API's output
lines up with what the UI already expects.

**Demo login:** `demo@smarterjobhunt.dev` / `demopassword123`

## 4. Run it

```bash
python app.py
```

Serves on `http://localhost:5000`. `GET /api/health` should return `{"status": "ok"}`.

## Endpoints

| Method | Path                          | Auth     | Purpose |
|--------|-------------------------------|----------|---------|
| POST   | `/api/auth/register`          | —        | Create an account |
| POST   | `/api/auth/login`             | —        | Returns a bearer token |
| GET    | `/api/auth/me`                | required | Current user |
| GET    | `/api/jobs`                   | optional | List/filter jobs — `?title=&posted_days=&funding=both\|a\|b&limit=&offset=` |
| GET    | `/api/companies/<id>/jobs`    | optional | All jobs at one company ("See them all") |
| PUT    | `/api/job-status/<job_id>`    | required | Set Applied/Rejected (+ reason) |
| DELETE | `/api/job-status/<job_id>`    | required | Clear a status |
| GET    | `/api/saved-searches`         | required | List saved searches |
| POST   | `/api/saved-searches`         | required | Save a new search |
| DELETE | `/api/saved-searches/<id>`    | required | Delete a saved search |

Send the token from login/register as `Authorization: Bearer <token>`. Match
percentages and applied/rejected status only appear on `/api/jobs` when
authenticated — logged-out browsing still returns listings, just without
personalization.

## Where the scraping agent plugs in

The agent's job is to `INSERT`/`UPDATE` rows in `jobs` (and `companies` as new
employers show up) — that's the whole integration surface. Nothing else in
this API needs to change when that's wired up. `job_matches.match_percent` is
similarly meant to be populated by whatever computes resume-fit later; until
then the API just returns `null` for it.

## Connecting the React frontend

Point fetch calls at `http://localhost:5000` in dev (e.g. via a `VITE_API_URL`
env var) and add `credentials: 'omit'` with the bearer token in an
`Authorization` header — no cookie/session plumbing needed. Happy to wire this
up when you're ready.
