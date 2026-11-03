\set ON_ERROR_STOP on
\timing on

\echo '== Connection =='
SELECT current_user AS user, current_database() AS db;

\echo '== Schemas =='
SELECT nspname
FROM pg_namespace
WHERE nspname IN ('simulators','jobs','results','evaluations','system_discovery')
ORDER BY 1;

\echo '== Enum types (simulators.param_direction, simulators.param_type) =='
SELECT n.nspname AS schema, t.typname AS type_name
FROM pg_type t
JOIN pg_namespace n ON n.oid = t.typnamespace
WHERE n.nspname = 'simulators'
  AND t.typname IN ('param_direction','param_type')
ORDER BY 1, 2;

\echo '== Enum labels: simulators.param_direction =='
SELECT e.enumlabel
FROM pg_type t
JOIN pg_namespace n ON n.oid = t.typnamespace
JOIN pg_enum e ON e.enumtypid = t.oid
WHERE n.nspname = 'simulators' AND t.typname = 'param_direction'
ORDER BY e.enumsortorder;

\echo '== Enum labels: simulators.param_type =='
SELECT e.enumlabel
FROM pg_type t
JOIN pg_namespace n ON n.oid = t.typnamespace
JOIN pg_enum e ON e.enumtypid = t.oid
WHERE n.nspname = 'simulators' AND t.typname = 'param_type'
ORDER BY e.enumsortorder;

\echo '== Tables =='
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema IN ('simulators','jobs','results','evaluations','system_discovery')
ORDER BY table_schema, table_name;

-- Fail rather than merely print an empty catalog when initialization is incomplete.
DO $$
DECLARE
  required_table TEXT;
BEGIN
  FOREACH required_table IN ARRAY ARRAY[
    'simulators.simulator', 'simulators.param_def', 'jobs.job', 'results.result',
    'evaluations.evaluation', 'evaluations.evaluation_job',
    'system_discovery.training', 'system_discovery.saved_model', 'system_discovery.simulation'
  ] LOOP
    IF to_regclass(required_table) IS NULL THEN
      RAISE EXCEPTION 'Required table is missing: %', required_table;
    END IF;
  END LOOP;
END;
$$;

\echo '== Columns quick check =='
-- simulators.simulator
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema='simulators' AND table_name='simulator'
ORDER BY ordinal_position;

-- simulators.param_def
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema='simulators' AND table_name='param_def'
ORDER BY ordinal_position;

-- results.result
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema='results' AND table_name='result'
ORDER BY ordinal_position;

\echo '== Constraints =='
SELECT
  conrelid::regclass AS table_name,
  conname,
  contype
FROM pg_constraint
WHERE conrelid::regclass::text IN (
  'simulators.simulator',
  'simulators.param_def',
  'results.result'
)
ORDER BY 1, 3, 2;

\echo '== search_path setting for role in this DB =='
SELECT
  r.rolname,
  d.datname,
  unnest(s.setconfig) AS configuration
FROM pg_db_role_setting s
JOIN pg_roles r ON r.oid = s.setrole
JOIN pg_database d ON d.oid = s.setdatabase
WHERE r.rolname = current_user
  AND d.datname = current_database();

\echo '== Optional: smoke-test insert (ROLLBACK) =='
BEGIN;

-- Insert a simulator
INSERT INTO simulators.simulator
(model_name, version, image_reference_url, image_digest, image_tags)
VALUES
('__sanity_sim__', '0', 'url', 'digest', '{}'::jsonb)
RETURNING simulator_id;

-- Insert param defs (unified)
-- 2 required inputs + 1 output (time series) definition
INSERT INTO simulators.param_def (simulator_id, direction, name, ptype, required, ordinal)
SELECT simulator_id, 'input',  'p_int', 'int',    true,  1
FROM simulators.simulator
WHERE model_name='__sanity_sim__' AND version='0';

INSERT INTO simulators.param_def (simulator_id, direction, name, ptype, required, ordinal)
SELECT simulator_id, 'input',  'p_str', 'str',    true,  2
FROM simulators.simulator
WHERE model_name='__sanity_sim__' AND version='0';

INSERT INTO simulators.param_def (simulator_id, direction, name, ptype, required, ordinal)
SELECT simulator_id, 'output', 'y_ts',  'float_ts', true,  1
FROM simulators.simulator
WHERE model_name='__sanity_sim__' AND version='0';

-- Match the current result schema: simulator_id belongs to jobs.job.
INSERT INTO results.result (job_id, res_id, url)
VALUES (999999, 1, 'https://example.invalid/results/999999/1/results.csv.zip');

ROLLBACK;

\echo '== Sanity check finished OK =='
