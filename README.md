# Arts Opportunity Intelligence — core pipeline (v0.1)

Fetches arts-agency and public-art sources, extracts opportunities with Claude, checks every
extracted value against the page it came from, assigns a conservative status, builds a
backward work plan from each deadline, and publishes a calendar feed.

## What runs each day (`python -m ai.run daily`)
1. **fetch**: checks due sources (respecting robots.txt), stores a snapshot only when the page text changed.
2. **extract**: sends changed pages to Claude Haiku with a strict schema. Every value must come with a
   verbatim quote. Quotes that can't be found on the page are rejected and the value is dropped.
   Links that look like specific calls are added as *inactive* sources for your approval.
3. **verify**: an opportunity is ACTIVE only with a confirmed, future deadline from an official (P1)
   source and a current cycle. Everything else is REQUIRES_VERIFICATION, UPCOMING, CLOSED, EXPIRED or CANCELED.
4. **calendar**: writes `calendar.ics` (deadlines, plus work-plan milestones once you move an
   opportunity past NEW). Anything not fully confirmed is labeled `[VERIFY]`.

## Setup (no local Python needed)
1. **Supabase**: create a project → Database → Extensions → enable `vector` and `postgis`.
   SQL Editor → run `sql/01_schema.sql`, then `sql/02_seed_reference.sql`.
   Then run `sql/03_seed_sources.sql` to load the 60 seed sources. (Don't import the CSV through the Table Editor; its columns don't match.)
2. **Connection string**: in Supabase click **Connect** and copy the **Session pooler** URI
   (GitHub's servers can't reach the direct IPv6 address). Put your database password in it.
3. **GitHub**: push this folder to a private repo. Settings → Secrets and variables → Actions:
   - Secrets: `DATABASE_URL`, `ANTHROPIC_API_KEY`
   - Optional secrets for a hosted calendar: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
     (and create a **public** Storage bucket named `calendar`)
   - Variable: `USER_AGENT` = `ArtsIntelligenceBot/0.1 (research; contact: your@email)`
4. (Skip if you ran 03_seed_sources.sql.) Actions tab → **one-time-setup** loads the sources as an alternative.
5. Actions tab → **daily-scan** → Run workflow to test. After that it runs every morning.
6. Calendar: subscribe to
   `https://YOUR_PROJECT.supabase.co/storage/v1/object/public/calendar/arts.ics`
   in Google Calendar (Other calendars → From URL).

## Reviewing results (until the dashboard exists)
In Supabase Table Editor:
- `opportunities`: filter `validity = REQUIRES_VERIFICATION` to see what needs a human check.
  Set `stage` to RESEARCHING (etc.) to put its milestones on your calendar.
- `claims`: every value with its supporting quote and confidence.
- `sources`: rows with `active = false` and `discovered_via = link_from_source:*` are proposed
  new sources. Set `active = true` to approve.
- `job_runs`: run history, token use, estimated cost, errors.

## Cost controls
`MAX_SOURCES_PER_RUN` (default 80) and `MAX_EXTRACTIONS_PER_RUN` (default 60) cap each run.
Unchanged pages never reach the model. Set a monthly spend limit in the Anthropic console too.
Update `PRICE_PER_MTOK` in `ai/config.py` to current pricing for accurate cost estimates.

## Tests
`pytest -q tests` (logic tests). The integration test runs against a real Postgres when
`TEST_DATABASE_URL` is set.

## Not built yet
Dashboard, alert emails, weekly report, community profiles, concept generator, partner scout,
search-API source discovery, newsletter ingestion, embedding-based dedup.
