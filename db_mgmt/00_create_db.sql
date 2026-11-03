\set ON_ERROR_STOP on

-- Required psql vars:
--   db_name
--   owner_role

-- Compute a boolean flag for psql \if
SELECT NOT EXISTS (
  SELECT 1 FROM pg_roles WHERE rolname = :'owner_role'
) AS role_missing;
\gset

\if :role_missing
  \echo ERROR: Role ":owner_role" does not exist. Create it first.
  \quit 1
\endif

-- Create database only if missing (uses \gexec; safe outside transaction)
SELECT format('CREATE DATABASE %I OWNER %I;', :'db_name', :'owner_role')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db_name');
\gexec