-- =====================================================================
-- National Arts Opportunity & Partnership Intelligence System
-- MVP schema — PostgreSQL 15+ (Supabase / Neon compatible)
-- Extensions: pgvector (semantic dedup + search), PostGIS (network map)
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- fuzzy title matching for dedup

-- ---------------------------------------------------------------------
-- ENUMS
-- ---------------------------------------------------------------------
CREATE TYPE confidence_level AS ENUM ('CONFIRMED','PROBABLE','INFERRED','UNKNOWN');

CREATE TYPE validity_status AS ENUM (
  'ACTIVE',                 -- verified open, current cycle, deadline in future
  'UPCOMING',               -- announced / recurring cycle expected, not yet open
  'REQUIRES_VERIFICATION',  -- default for anything not yet checked against a primary source
  'CLOSED','CANCELED','EXPIRED'
);

CREATE TYPE pipeline_stage AS ENUM (
  'NEW','RESEARCHING','PARTNER_SEARCH','PARTNER_CONFIRMED','CONCEPT_DEVELOPMENT',
  'APPLICATION_IN_PROGRESS','READY_TO_SUBMIT','SUBMITTED','AWARDED','DECLINED','ARCHIVED'
);

CREATE TYPE source_tier AS ENUM (
  'P1_OFFICIAL',            -- government, official grant pages, universities, official project docs
  'P2_PRESS_PROFESSIONAL',  -- established local news, industry pubs, professional orgs
  'P3_SECONDARY_DB',        -- aggregators / grant databases
  'P4_SOCIAL'
);

CREATE TYPE source_category AS ENUM (
  'FEDERAL','STATE','REGIONAL','MUNICIPAL','INSTITUTIONAL','PRIVATE','AGGREGATOR','PROCUREMENT','NEWS'
);

CREATE TYPE fetch_method AS ENUM ('API','RSS','HTML','HTML_JS','PDF','EMAIL_NEWSLETTER','MANUAL');

CREATE TYPE need_basis AS ENUM ('DOCUMENTED','AI_INFERRED');

CREATE TYPE methodology AS ENUM ('NATURE','EMBODIED','CULTURAL_EMERGENCE');

CREATE TYPE complexity_level AS ENUM ('LOW','MEDIUM','HIGH');

CREATE TYPE relationship_status AS ENUM (
  'IDENTIFIED','RESEARCHED','CONTACTED','IN_CONVERSATION','COLLABORATING','PAST_COLLABORATOR','NOT_A_FIT'
);

CREATE TYPE actor_kind AS ENUM ('HUMAN','AGENT');

-- ---------------------------------------------------------------------
-- GEOGRAPHY
-- ---------------------------------------------------------------------
CREATE TABLE places (
  id           BIGSERIAL PRIMARY KEY,
  name         TEXT NOT NULL,                -- "Shreveport–Bossier", "Hilo"
  place_kind   TEXT NOT NULL DEFAULT 'city', -- city | metro | county | state | region
  state_code   CHAR(2),
  region       TEXT,                         -- Census region or RAO region
  county       TEXT,
  geom         GEOGRAPHY(POINT, 4326),
  is_target    BOOLEAN NOT NULL DEFAULT FALSE,  -- in the user's focus list
  UNIQUE (name, state_code, place_kind)
);

-- ---------------------------------------------------------------------
-- ORGANIZATIONS (shared: funders, issuers, partners, community orgs)
-- ---------------------------------------------------------------------
CREATE TABLE organizations (
  id           BIGSERIAL PRIMARY KEY,
  name         TEXT NOT NULL,
  org_type     TEXT NOT NULL,   -- federal_agency | state_arts_agency | city_dept | university | fabricator | av_company | foundation | nonprofit | developer | ...
  website      TEXT,
  place_id     BIGINT REFERENCES places(id),
  address      TEXT,
  geom         GEOGRAPHY(POINT, 4326),
  notes        TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX organizations_name_site ON organizations (lower(name), coalesce(lower(website),''));

-- ---------------------------------------------------------------------
-- SOURCES & SNAPSHOTS (everything traceable back to a captured page)
-- ---------------------------------------------------------------------
CREATE TABLE sources (
  id               BIGSERIAL PRIMARY KEY,
  name             TEXT NOT NULL,
  url              TEXT NOT NULL UNIQUE,
  organization_id  BIGINT REFERENCES organizations(id),
  tier             source_tier NOT NULL,
  category         source_category NOT NULL,
  place_id         BIGINT REFERENCES places(id),          -- jurisdiction
  fetch_method     fetch_method NOT NULL DEFAULT 'HTML',
  check_every      INTERVAL NOT NULL DEFAULT '7 days',
  robots_allowed   BOOLEAN,                               -- NULL = not yet checked
  tos_notes        TEXT,                                  -- e.g., "no automated access; manual only"
  discovered_via   TEXT,                                  -- seed | search_api | link_from_source:<id> | newsletter
  active           BOOLEAN NOT NULL DEFAULT TRUE,
  last_fetched_at  TIMESTAMPTZ,
  last_changed_at  TIMESTAMPTZ,
  last_content_hash TEXT,
  consecutive_failures INT NOT NULL DEFAULT 0,
  yield_score      NUMERIC,           -- opportunities found / fetches; used to tune frequency
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE source_snapshots (
  id            BIGSERIAL PRIMARY KEY,
  source_id     BIGINT REFERENCES sources(id),
  url           TEXT NOT NULL,          -- may be a detail page under the source
  fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  http_status   INT,
  content_hash  TEXT NOT NULL,          -- sha256 of normalized text
  storage_path  TEXT,                   -- object storage key for raw HTML/PDF
  clean_text    TEXT,                   -- normalized text used for extraction + citation offsets
  changed       BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX ON source_snapshots (source_id, fetched_at DESC);

-- ---------------------------------------------------------------------
-- OPPORTUNITIES
-- ---------------------------------------------------------------------
CREATE TABLE opportunity_types ( code TEXT PRIMARY KEY, label TEXT NOT NULL );
-- e.g. grant, rfq, rfp, rfa, commission, residency, fellowship, competition, research_call, capital_project_signal

CREATE TABLE mediums ( code TEXT PRIMARY KEY, label TEXT NOT NULL );
-- e.g. sculpture, mural, projection, light, digital, installation, interactive, environmental_graphics, sound

CREATE TABLE opportunities (
  id                 BIGSERIAL PRIMARY KEY,
  name               TEXT NOT NULL,
  issuer_org_id      BIGINT REFERENCES organizations(id),
  place_id           BIGINT REFERENCES places(id),
  opportunity_type   TEXT REFERENCES opportunity_types(code),
  funding_type       TEXT,               -- grant | commission_fee | contract | stipend | in_kind
  description        TEXT,
  community_served   TEXT,
  applicant_eligibility TEXT,
  artist_eligibility TEXT,
  required_partners  TEXT,
  funding_min        NUMERIC,
  funding_max        NUMERIC,
  total_project_budget NUMERIC,
  artist_budget      NUMERIC,
  match_requirement  TEXT,
  project_timeline   TEXT,
  installation_timeline TEXT,
  application_requirements TEXT,
  required_documents TEXT[],
  relevant_technologies TEXT[],
  contact_name       TEXT,
  contact_info       TEXT,
  source_url         TEXT NOT NULL,
  -- status & quality
  validity           validity_status NOT NULL DEFAULT 'REQUIRES_VERIFICATION',
  overall_confidence confidence_level NOT NULL DEFAULT 'UNKNOWN',
  stage              pipeline_stage NOT NULL DEFAULT 'NEW',
  discovered_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_verified_at   TIMESTAMPTZ,
  next_review_at     TIMESTAMPTZ,
  cycle_label        TEXT,               -- "FY2027", "2026 Spring"
  is_recurring       BOOLEAN,
  -- dedup / search
  fingerprint        TEXT,               -- normalized(issuer|name|cycle|deadline)
  embedding          vector(1024),
  search_tsv         tsvector GENERATED ALWAYS AS (
                       to_tsvector('english', coalesce(name,'') || ' ' || coalesce(description,''))
                     ) STORED,
  duplicate_of       BIGINT REFERENCES opportunities(id),
  notes              TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON opportunities USING gin (search_tsv);
CREATE INDEX ON opportunities USING gin (name gin_trgm_ops);
CREATE INDEX ON opportunities (validity, stage);
CREATE INDEX ON opportunities (next_review_at);

CREATE TABLE opportunity_mediums (
  opportunity_id BIGINT REFERENCES opportunities(id) ON DELETE CASCADE,
  medium_code    TEXT REFERENCES mediums(code),
  basis          confidence_level NOT NULL,     -- stated in call vs inferred
  PRIMARY KEY (opportunity_id, medium_code)
);

-- Field-level provenance: the anti-fabrication backbone.
-- Every important value on an opportunity (deadline, amount, eligibility, status)
-- must trace to a claim with a quoted snippet from a stored snapshot.
CREATE TABLE claims (
  id             BIGSERIAL PRIMARY KEY,
  entity_table   TEXT NOT NULL,     -- 'opportunities' | 'organizations' | 'communities' | ...
  entity_id      BIGINT NOT NULL,
  field_name     TEXT NOT NULL,     -- 'deadline', 'funding_max', 'artist_eligibility', ...
  value_text     TEXT,
  value_json     JSONB,
  confidence     confidence_level NOT NULL,
  snapshot_id    BIGINT REFERENCES source_snapshots(id),
  quote          TEXT,              -- exact supporting text (short); NULL only if INFERRED/UNKNOWN
  quote_start    INT,               -- char offsets into snapshot.clean_text
  quote_end      INT,
  extracted_by   actor_kind NOT NULL,
  model          TEXT,
  superseded_by  BIGINT REFERENCES claims(id),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (confidence IN ('INFERRED','UNKNOWN') OR (snapshot_id IS NOT NULL AND quote IS NOT NULL))
);
CREATE INDEX ON claims (entity_table, entity_id, field_name) WHERE superseded_by IS NULL;

-- Change log (deadline moved, funding changed, canceled, etc.)
CREATE TABLE opportunity_changes (
  id              BIGSERIAL PRIMARY KEY,
  opportunity_id  BIGINT REFERENCES opportunities(id) ON DELETE CASCADE,
  field_name      TEXT NOT NULL,
  old_value       TEXT,
  new_value       TEXT,
  detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  snapshot_id     BIGINT REFERENCES source_snapshots(id),
  alerted         BOOLEAN NOT NULL DEFAULT FALSE
);

-- Transparent assessment (no black-box score). Each dimension gets a 0–3 rating
-- against a published rubric plus a written rationale.
CREATE TABLE opportunity_assessments (
  id              BIGSERIAL PRIMARY KEY,
  opportunity_id  BIGINT REFERENCES opportunities(id) ON DELETE CASCADE,
  dimension       TEXT NOT NULL CHECK (dimension IN (
                    'artistic','financial','geographic_expansion','portfolio','relationship',
                    'technical_development','community_impact','institutional_credibility','future_commissions',
                    'practice_fit','practice_expansion','application_effort')),
  rating          SMALLINT CHECK (rating BETWEEN 0 AND 3),
  rationale       TEXT NOT NULL,
  rubric_version  TEXT NOT NULL,
  assessed_by     actor_kind NOT NULL,
  model           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- DEADLINES & INTERNAL MILESTONES
-- ---------------------------------------------------------------------
CREATE TABLE deadlines (
  id              BIGSERIAL PRIMARY KEY,
  opportunity_id  BIGINT REFERENCES opportunities(id) ON DELETE CASCADE,
  kind            TEXT NOT NULL,    -- application | intent_to_apply | loi | info_session | qa_cutoff | registration (SAM/UEI) | award_notice
  due_at          TIMESTAMPTZ,      -- stored in UTC
  local_timezone  TEXT,             -- IANA tz from the call, e.g. 'America/Chicago'
  confidence      confidence_level NOT NULL,
  claim_id        BIGINT REFERENCES claims(id)
);
CREATE INDEX ON deadlines (due_at);

CREATE TABLE milestones (
  id              BIGSERIAL PRIMARY KEY,
  opportunity_id  BIGINT REFERENCES opportunities(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,    -- Research | Identify partners | Contact partners | Concept | Budget | Draft | Partner review | Final review | Submission prep
  due_date        DATE NOT NULL,
  sequence        SMALLINT NOT NULL,
  completed_at    TIMESTAMPTZ,
  auto_generated  BOOLEAN NOT NULL DEFAULT TRUE,
  compressed      BOOLEAN NOT NULL DEFAULT FALSE   -- TRUE when the runway was too short for the standard plan
);

-- ---------------------------------------------------------------------
-- COMMUNITY INTELLIGENCE
-- ---------------------------------------------------------------------
CREATE TABLE community_profiles (
  id              BIGSERIAL PRIMARY KEY,
  place_id        BIGINT REFERENCES places(id) UNIQUE,
  summary         TEXT,             -- synthesized, citation-linked
  last_researched_at TIMESTAMPTZ,
  next_review_at  TIMESTAMPTZ,
  reviewed_by_human BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE community_facts (
  id              BIGSERIAL PRIMARY KEY,
  profile_id      BIGINT REFERENCES community_profiles(id) ON DELETE CASCADE,
  category        TEXT NOT NULL CHECK (category IN ('geography','history','culture','contemporary')),
  subcategory     TEXT,             -- 'indigenous_history','rivers','music','festivals','development',...
  statement       TEXT NOT NULL,
  confidence      confidence_level NOT NULL,
  snapshot_id     BIGINT REFERENCES source_snapshots(id),
  quote           TEXT,
  source_is_local BOOLEAN,          -- prioritize local/primary voices
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE community_needs (
  id              BIGSERIAL PRIMARY KEY,
  profile_id      BIGINT REFERENCES community_profiles(id) ON DELETE CASCADE,
  need_type       TEXT NOT NULL,    -- gathering_space | youth_engagement | wayfinding | historic_preservation | ...
  description     TEXT NOT NULL,
  basis           need_basis NOT NULL,
  stated_by       TEXT,             -- which institution/resident body stated it (DOCUMENTED only)
  document_title  TEXT,             -- e.g., "2024 Downtown Master Plan"
  snapshot_id     BIGINT REFERENCES source_snapshots(id),
  quote           TEXT,
  CHECK (basis = 'AI_INFERRED' OR (snapshot_id IS NOT NULL AND quote IS NOT NULL AND stated_by IS NOT NULL))
);

-- ---------------------------------------------------------------------
-- ARTISTIC CONCEPTS
-- ---------------------------------------------------------------------
CREATE TABLE concepts (
  id                 BIGSERIAL PRIMARY KEY,
  opportunity_id     BIGINT REFERENCES opportunities(id) ON DELETE CASCADE,
  profile_id         BIGINT REFERENCES community_profiles(id),
  title              TEXT NOT NULL,
  core_idea          TEXT NOT NULL,
  community_connection TEXT NOT NULL,
  methodologies      methodology[] NOT NULL,
  nature_process     TEXT,          -- the generative process (not imagery), if NATURE
  physical_experience TEXT NOT NULL,-- PERSON + SPACE + MATERIAL + MOVEMENT + ENVIRONMENT
  emergence_inputs   TEXT,          -- what community inputs the work would be built from, if CULTURAL_EMERGENCE
  materials          TEXT[],
  production_requirements TEXT[],   -- fabricator, engineer, projection, AV, university, ...
  complexity         complexity_level NOT NULL,
  scalability        TEXT,
  rough_budget_low   NUMERIC,
  rough_budget_high  NUMERIC,
  budget_basis       TEXT,          -- how the estimate was reached; always INFERRED
  status             TEXT NOT NULL DEFAULT 'draft',  -- draft | shortlisted | developing | rejected
  generated_by       actor_kind NOT NULL,
  model              TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE concept_needs (      -- which need(s) a concept responds to, keeping DOCUMENTED vs INFERRED visible
  concept_id  BIGINT REFERENCES concepts(id) ON DELETE CASCADE,
  need_id     BIGINT REFERENCES community_needs(id) ON DELETE CASCADE,
  PRIMARY KEY (concept_id, need_id)
);

-- ---------------------------------------------------------------------
-- PARTNERSHIP INTELLIGENCE
-- ---------------------------------------------------------------------
CREATE TABLE partner_profiles (
  organization_id    BIGINT PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
  capabilities       TEXT[] NOT NULL,   -- metal_fabrication | acrylic | large_format_vinyl | projection_mapping | av_integration | structural_engineering | ...
  service_radius_mi  INT,
  relationship       relationship_status NOT NULL DEFAULT 'IDENTIFIED',
  public_contact     TEXT,              -- only if publicly listed
  last_researched_at TIMESTAMPTZ,
  next_review_at     TIMESTAMPTZ
);

CREATE TABLE partner_evidence (      -- no capability or past project without evidence
  id              BIGSERIAL PRIMARY KEY,
  organization_id BIGINT REFERENCES organizations(id) ON DELETE CASCADE,
  kind            TEXT NOT NULL,       -- capability | past_project | award | certification
  statement       TEXT NOT NULL,
  snapshot_id     BIGINT REFERENCES source_snapshots(id) NOT NULL,
  quote           TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE opportunity_partner_matches (
  id                BIGSERIAL PRIMARY KEY,
  opportunity_id    BIGINT REFERENCES opportunities(id) ON DELETE CASCADE,
  concept_id        BIGINT REFERENCES concepts(id),
  organization_id   BIGINT REFERENCES organizations(id),
  proposed_role     TEXT NOT NULL,     -- fabrication | engineering | community_partner | academic_partner | AV | lead_applicant | ...
  fills_gap         TEXT NOT NULL,     -- which required capability this complements
  rationale         TEXT NOT NULL,
  evidence_ids      BIGINT[],          -- partner_evidence rows supporting the match
  status            TEXT NOT NULL DEFAULT 'suggested',  -- suggested | accepted | contacted | confirmed | rejected
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE interactions (           -- CRM-lite; also feeds the learning loop
  id               BIGSERIAL PRIMARY KEY,
  organization_id  BIGINT REFERENCES organizations(id),
  opportunity_id   BIGINT REFERENCES opportunities(id),
  occurred_at      TIMESTAMPTZ NOT NULL,
  channel          TEXT,               -- email | call | meeting | event
  direction        TEXT,               -- outbound | inbound
  summary          TEXT,
  outcome          TEXT,               -- no_response | positive | declined | follow_up
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- APPLICATIONS, PROJECTS, LEARNING SIGNALS
-- ---------------------------------------------------------------------
CREATE TABLE applications (
  id               BIGSERIAL PRIMARY KEY,
  opportunity_id   BIGINT REFERENCES opportunities(id),
  concept_id       BIGINT REFERENCES concepts(id),
  submitted_at     TIMESTAMPTZ,
  amount_requested NUMERIC,
  outcome          TEXT,               -- pending | awarded | declined | withdrawn
  award_amount     NUMERIC,
  feedback         TEXT,
  lessons          TEXT
);

CREATE TABLE user_actions (           -- explicit, inspectable signals; no hidden preference model
  id              BIGSERIAL PRIMARY KEY,
  entity_table    TEXT NOT NULL,
  entity_id       BIGINT NOT NULL,
  action          TEXT NOT NULL,        -- pursued | dismissed | starred | stage_change | contacted | note
  reason          TEXT,                 -- user-supplied; dismissals ask for a one-line reason
  from_stage      pipeline_stage,
  to_stage        pipeline_stage,
  occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE preference_rules (       -- learned preferences are written as readable rules the user can edit
  id              BIGSERIAL PRIMARY KEY,
  rule_text       TEXT NOT NULL,        -- "Down-rank mural-only calls under $15k (dismissed 9 of 10)"
  evidence        TEXT NOT NULL,
  active          BOOLEAN NOT NULL DEFAULT FALSE,  -- proposed by agent, activated by user
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- REPORTS & JOB RUNS
-- ---------------------------------------------------------------------
CREATE TABLE reports (
  id            BIGSERIAL PRIMARY KEY,
  kind          TEXT NOT NULL CHECK (kind IN ('weekly','monthly','alert')),
  period_start  DATE,
  period_end    DATE,
  body_md       TEXT NOT NULL,
  generated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE job_runs (               -- monitoring + cost control
  id            BIGSERIAL PRIMARY KEY,
  job           TEXT NOT NULL,
  started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at   TIMESTAMPTZ,
  status        TEXT,
  items_in      INT,
  items_out     INT,
  llm_input_tokens  BIGINT,
  llm_output_tokens BIGINT,
  est_cost_usd  NUMERIC(10,4),
  error         TEXT
);

-- ---------------------------------------------------------------------
-- VIEWS FOR THE DASHBOARD
-- ---------------------------------------------------------------------
CREATE VIEW v_upcoming_deadlines AS
SELECT o.id, o.name, p.name AS place, p.state_code, d.kind, d.due_at, d.local_timezone, d.confidence,
       o.validity, o.stage,
       CASE WHEN d.due_at < now() + interval '7 days'  THEN 'this_week'
            WHEN d.due_at < now() + interval '30 days' THEN 'next_30'
            WHEN d.due_at < now() + interval '90 days' THEN 'next_90'
            ELSE 'later' END AS bucket
FROM deadlines d
JOIN opportunities o ON o.id = d.opportunity_id
LEFT JOIN places p ON p.id = o.place_id
WHERE d.due_at > now() AND o.validity IN ('ACTIVE','UPCOMING','REQUIRES_VERIFICATION')
  AND o.duplicate_of IS NULL;

CREATE VIEW v_network_by_place AS
SELECT p.id AS place_id, p.name, p.state_code,
  (SELECT count(*) FROM opportunities o WHERE o.place_id = p.id AND o.validity IN ('ACTIVE','UPCOMING')) AS opportunities,
  (SELECT count(*) FROM organizations g JOIN partner_profiles pp ON pp.organization_id = g.id
     WHERE g.place_id = p.id AND 'metal_fabrication' = ANY(pp.capabilities)) AS fabricators,
  (SELECT count(*) FROM organizations g JOIN partner_profiles pp ON pp.organization_id = g.id
     WHERE g.place_id = p.id AND 'projection_mapping' = ANY(pp.capabilities)) AS projection_companies,
  (SELECT count(*) FROM organizations g WHERE g.place_id = p.id AND g.org_type = 'university') AS universities,
  (SELECT count(*) FROM organizations g JOIN partner_profiles pp ON pp.organization_id = g.id
     WHERE g.place_id = p.id AND pp.relationship IN ('IN_CONVERSATION','COLLABORATING')) AS active_conversations,
  (SELECT count(*) FROM opportunities o WHERE o.place_id = p.id
     AND o.stage IN ('APPLICATION_IN_PROGRESS','READY_TO_SUBMIT','SUBMITTED','AWARDED')) AS projects_pursued
FROM places p WHERE p.is_target;
