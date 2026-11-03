\set ON_ERROR_STOP on

-- Required psql vars:
--   db_name
--   owner_role

-- Schemas
CREATE SCHEMA IF NOT EXISTS simulators AUTHORIZATION :"owner_role";
CREATE SCHEMA IF NOT EXISTS jobs       AUTHORIZATION :"owner_role";
CREATE SCHEMA IF NOT EXISTS results    AUTHORIZATION :"owner_role";
CREATE SCHEMA IF NOT EXISTS system_discovery AUTHORIZATION :"owner_role";
CREATE SCHEMA IF NOT EXISTS evaluations AUTHORIZATION :"owner_role";

-- Make search_path nice for that role in this DB
SELECT format(
  'ALTER ROLE %I IN DATABASE %I SET search_path = simulators, results, evaluations, public;',
  :'owner_role',
  :'db_name'
)
\gexec

-- Enums (only if missing)
SELECT
  'CREATE TYPE simulators.param_direction AS ENUM (''input'', ''output'');'
WHERE NOT EXISTS (
  SELECT 1
  FROM pg_type t
  JOIN pg_namespace n ON n.oid = t.typnamespace
  WHERE t.typname = 'param_direction' AND n.nspname = 'simulators'
)
\gexec

SELECT
  'CREATE TYPE simulators.param_type AS ENUM (''int'', ''float'', ''str'', ''bool'', ''int_ts'', ''float_ts'', ''str_ts'', ''bool_ts'');'
WHERE NOT EXISTS (
  SELECT 1
  FROM pg_type t
  JOIN pg_namespace n ON n.oid = t.typnamespace
  WHERE t.typname = 'param_type' AND n.nspname = 'simulators'
)
\gexec

-- Tables
CREATE TABLE IF NOT EXISTS simulators.simulator (
  simulator_id BIGSERIAL PRIMARY KEY,
  model_name TEXT NOT NULL,
  version TEXT NOT NULL,
  image_reference_url TEXT NOT NULL,
  image_digest TEXT NOT NULL,
  image_tags JSONB NOT NULL,
  UNIQUE (model_name, version)
);

-- Unified parameter definition table (input + output)
CREATE TABLE IF NOT EXISTS simulators.param_def (
  param_id BIGSERIAL PRIMARY KEY,
  simulator_id BIGINT NOT NULL REFERENCES simulators.simulator(simulator_id) ON DELETE CASCADE,

  direction simulators.param_direction NOT NULL,   -- input/output
  name TEXT NOT NULL,
  ptype simulators.param_type NOT NULL,            -- includes *_ts types

  required BOOLEAN NOT NULL DEFAULT TRUE,
  ordinal INT NOT NULL DEFAULT 0,

  description TEXT,
  unit TEXT,

  UNIQUE (simulator_id, direction, name)
);

CREATE INDEX IF NOT EXISTS param_def_simulator_id_idx ON simulators.param_def (simulator_id);
CREATE INDEX IF NOT EXISTS param_def_direction_idx    ON simulators.param_def (direction);
CREATE INDEX IF NOT EXISTS param_def_ptype_idx        ON simulators.param_def (ptype);

-- System Discovery training registry
CREATE TABLE IF NOT EXISTS system_discovery.training (
  training_id TEXT PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ,
  state TEXT NOT NULL,
  raw_status TEXT NOT NULL,
  training_status TEXT,
  evaluation_status TEXT,
  error TEXT,
  basis TEXT NOT NULL,
  degree INT NOT NULL,
  model TEXT NOT NULL,
  nlags_x JSONB NOT NULL,
  nlags_y INT NOT NULL,
  results_archive_path TEXT,
  results_cached_at TIMESTAMPTZ,
  results_cache_error TEXT,
  finished_at TIMESTAMPTZ,
  archived_at TIMESTAMPTZ
);

ALTER TABLE system_discovery.training
  ADD COLUMN IF NOT EXISTS results_archive_path TEXT,
  ADD COLUMN IF NOT EXISTS results_cached_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS results_cache_error TEXT,
  ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS system_discovery_training_created_at_idx
  ON system_discovery.training (created_at DESC);

CREATE TABLE IF NOT EXISTS system_discovery.saved_model (
  model_id TEXT PRIMARY KEY,
  source_training_id TEXT NOT NULL UNIQUE,
  model_name TEXT NOT NULL,
  saved_at TIMESTAMPTZ NOT NULL,
  nlags_x JSONB NOT NULL,
  nlags_y INT NOT NULL,
  basis TEXT NOT NULL,
  degree INT NOT NULL
);

CREATE INDEX IF NOT EXISTS system_discovery_saved_model_saved_at_idx
  ON system_discovery.saved_model (saved_at DESC);

CREATE TABLE IF NOT EXISTS system_discovery.simulation (
  simulation_id TEXT PRIMARY KEY,
  source_model_id TEXT NOT NULL,
  source_model_name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ,
  state TEXT NOT NULL,
  raw_status TEXT NOT NULL,
  error TEXT,
  horizon INT,
  initial_conditions JSONB,
  uses_external_control_signals BOOLEAN NOT NULL DEFAULT FALSE,
  aistor_object_key TEXT,
  aistor_uploaded_at TIMESTAMPTZ,
  aistor_upload_error TEXT,
  visualization_plot_id TEXT
);

ALTER TABLE system_discovery.simulation
  ADD COLUMN IF NOT EXISTS uses_external_control_signals BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS aistor_object_key TEXT,
  ADD COLUMN IF NOT EXISTS aistor_uploaded_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS aistor_upload_error TEXT,
  ADD COLUMN IF NOT EXISTS visualization_plot_id TEXT;

CREATE INDEX IF NOT EXISTS system_discovery_simulation_created_at_idx
  ON system_discovery.simulation (created_at DESC);

-- Jobs tables
CREATE TABLE IF NOT EXISTS jobs.job (
  job_id BIGINT PRIMARY KEY,
  simulator_id BIGINT NOT NULL REFERENCES simulators.simulator(simulator_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  status TEXT NOT NULL DEFAULT 'created',
  results_root_url TEXT NOT NULL
);

-- Results tables
CREATE TABLE IF NOT EXISTS results.result (
  job_id BIGINT NOT NULL,
  res_id BIGINT NOT NULL,
  url TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (job_id, res_id)
);

-- Evaluations registry
-- One row per evaluation run. This is the source of truth for evaluation
-- progress; SSBO history is persisted per iteration so a running evaluation
-- can be rendered and resumed instead of only appearing once it finishes.
CREATE TABLE IF NOT EXISTS evaluations.evaluation (
  evaluation_id TEXT PRIMARY KEY,
  simulator_id  BIGINT NOT NULL REFERENCES simulators.simulator(simulator_id),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at   TIMESTAMPTZ,
  status        TEXT NOT NULL DEFAULT 'queued',
  stage         TEXT,
  iteration     INT NOT NULL DEFAULT 0,
  kmax          INT NOT NULL DEFAULT 30,
  best_value    DOUBLE PRECISION,
  best_params   JSONB,
  important_parameters JSONB,
  output_column TEXT,
  aggregation   TEXT,
  problem       JSONB,
  config        JSONB NOT NULL DEFAULT '{}'::jsonb,
  ssbo_history  JSONB NOT NULL DEFAULT '[]'::jsonb,
  final_result  JSONB,
  error         TEXT,
  CONSTRAINT evaluation_status_check CHECK (
    status IN (
      'queued', 'running', 'simulating', 'sensitivity_analysis',
      'optimizing', 'success', 'failed'
    )
  )
);

CREATE INDEX IF NOT EXISTS evaluations_evaluation_created_at_idx
  ON evaluations.evaluation (created_at DESC);

-- Hot path for "which evaluations are still in flight".
CREATE INDEX IF NOT EXISTS evaluations_evaluation_active_idx
  ON evaluations.evaluation (updated_at)
  WHERE status NOT IN ('success', 'failed');

-- Links every Slurm job an evaluation submitted back to that evaluation.
-- job_id deliberately has no FK to jobs.job, matching results.result: the row is
-- written at submit time and jobs.job is owned by a different service.
CREATE TABLE IF NOT EXISTS evaluations.evaluation_job (
  evaluation_id TEXT NOT NULL
    REFERENCES evaluations.evaluation(evaluation_id) ON DELETE CASCADE,
  job_id        BIGINT NOT NULL,
  stage         TEXT NOT NULL,
  iteration     INT NOT NULL DEFAULT 0,
  PRIMARY KEY (evaluation_id, job_id),
  CONSTRAINT evaluation_job_stage_check CHECK (
    stage IN ('sensitivity', 'ssbo')
  ),
  CONSTRAINT evaluation_job_iteration_check CHECK (iteration >= 0)
);

CREATE INDEX IF NOT EXISTS evaluations_evaluation_job_iteration_idx
  ON evaluations.evaluation_job (evaluation_id, iteration);
