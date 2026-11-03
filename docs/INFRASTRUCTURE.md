# Third-party infrastructure

Use this document to install and configure the systems required by RTMF,
then follow [Deployment](DEPLOYMENT.md) to start the application services. Reuse
existing systems when available; create the resources and accounts described
below instead of installing a second instance.

For the complete application on one isolated VM, start with
[Single-server VM setup](SINGLE_SERVER_VM.md) for placement, network rules,
host prerequisites, and the order in which to use these installation recipes.

Installation examples use Ubuntu/Debian, Bash, and systemd. Run each example on
the host named in its section. Replace `<...>` placeholders and `.example`
addresses before executing commands. Choose fixed dependency releases approved
for your site; this repository does not define a tested version matrix for the
entire external stack.

## What is needed, and where

| Dependency | Install on | Needed for |
| --- | --- | --- |
| Docker Engine + Compose plugin | Application hosts; Harbor/Keycloak host if using their container installers | Application containers and optional infrastructure containers. |
| PostgreSQL server | Database host or managed database | Simulator metadata, jobs, evaluations, and frontend System Discovery records. |
| PostgreSQL client (`psql`) | Host running `db_mgmt` commands | Initialize and check the application schema. |
| S3-compatible object storage, e.g. MinIO/AIStor | Storage host or existing S3 service | Results, parameter matrices, and System Discovery archives. |
| Keycloak | Identity host or existing identity installation | Frontend login and application permissions. Requires its own persistent database. |
| OCI registry, e.g. Harbor | Registry host or existing registry | Store worker bases and built simulator images; optionally application images. |
| BuildKit | Automatic Compose sidecar on the simulator-repository host | Build registered simulator images. No separate host install for normal deployment. |
| Slurm controller, compute daemons, client tools, and REST daemon | Cluster; compatible client tools on the scheduler application's host | Submit and inspect simulation job arrays. |
| Munge | Slurm authentication hosts and scheduler application's host | Authenticate the `scontrol` client used to obtain Slurm JWTs. |
| Apptainer | Every compute node that runs simulations | Run simulator/worker OCI images. |
| HTTPS reverse proxy, DNS, and certificates | Frontend/identity edge host or existing ingress | Public frontend and Keycloak URLs. Examples use Nginx. |
| MariaDB/MySQL, if the cluster uses `slurmdbd` accounting | Cluster accounting infrastructure | Slurm accounting, separate from RTMF's PostgreSQL database. |

Parser, visualization, and the standalone System Discovery API can run without
these database/cluster systems. Front and evaluator require the backend APIs
used by their workflows, locally or on other machines. There is no additional
Redis, RabbitMQ, or Celery server to provision for the shipped application.
See [the service dependency table](DEPLOYMENT.md#services-and-ports).

Prepare dependencies in this order:

1. [Docker, network reachability, and persistent storage locations](#docker-and-network-prerequisites).
2. [PostgreSQL application database and schema](#postgresql-one-application-database).
3. [S3 buckets and an application access key](#object-storage).
4. [Keycloak server/database](#keycloak-server), then its [realm, clients, roles, and users](KEYCLOAK.md).
5. [Simulator registry, accounts, and worker bases](#simulator-images-and-registry).
6. [Slurm REST/JWT, Munge, Apptainer, and work paths](#slurm-and-compute-nodes).
7. [HTTPS routing](#public-https-access), then [application startup and checks](#handoff-to-application-deployment).

## Docker and network prerequisites

Install Docker Engine and the Compose plugin using the
[official distribution instructions](https://docs.docker.com/engine/install/ubuntu/).
Check on every application host:

```sh
docker version
docker compose version
```

Both client and daemon must be available to the deployment account. Python 3.11+
is needed only where deployment configuration is rendered. Application Python
libraries are installed in application images.

Provide DNS names reachable from the **containers and compute nodes** that use
them. Container `localhost` refers to that container. Suggested addresses are:

| Address/port | Clients that must reach it |
| --- | --- |
| `postgres.example:5432` | Database-using application containers, worker containers, and Keycloak if it shares this PostgreSQL server. |
| `storage.example:9000` or an HTTPS S3 API | Application and compute/worker containers. The optional storage console is a different port, commonly `9001`. |
| `identity.example:443` | Browsers and front's in-process use-case layer. |
| `registry.example:5000` in the HTTP simulator-registry example | BuildKit, simulator repository digest lookups, and compute nodes. |
| `slurm.example:6820` | `jobs_scheduler`; this is the Slurm REST endpoint, not the RTMF scheduler API. |
| Slurm controller/compute ports configured by the cluster | Slurm nodes and submit clients; commonly controller `6817`, compute `6818`, and optional accounting `6819`. |
| `rtmf.example:443` | End users. The host reverse proxy reaches front on `127.0.0.1:63000`. |

BuildKit port `64000` stays on its Compose network. Application service ports
are listed in [Deployment](DEPLOYMENT.md#services-and-ports). The HTTP examples
below assume an internal deployment network; browser login uses HTTPS.

## PostgreSQL: one application database

### Install the server

On a new Ubuntu/Debian database host:

```sh
sudo apt update
sudo apt install -y postgresql postgresql-client
sudo systemctl enable --now postgresql
```

Use a supported PostgreSQL release provided by your distribution or the
[PostgreSQL package repository](https://www.postgresql.org/download/linux/ubuntu/).
For a managed database, obtain an administrator connection and skip this install.

Use one database, `rtmf`, for both framework DSNs. The schema has foreign
keys between simulator, job, and evaluation tables. Keycloak uses a **separate**
database; Slurm accounting, if enabled, uses its own database system.

### Create the account, then use `db_mgmt`

On the PostgreSQL host, connect as administrator:

```sh
sudo -u postgres psql
```

For a new installation, create the application login and set its password at the
interactive prompt. Existing installations should keep their existing role:

```sql
CREATE ROLE rtmf LOGIN;
\password rtmf
\q
```

Copy the repository's `db_mgmt` directory to this host if necessary. From the
repository/kit root, run in order:

```sh
export RTMF_DB_NAME=rtmf
export RTMF_DB_USER=rtmf
cd db_mgmt
bash db_config.sh
bash schema_creation.sh
bash sanity_check.sh
cd ..
```

The helpers expect their SQL files in the current directory, so the `cd` is
required. `db_config.sh` uses local `sudo -u postgres` to create the database
owned by the existing role. The other two connect to `localhost` and prompt for
that role's password. `RTMF_DB_*` variables configure these setup scripts; the
running application uses the DSNs described below.

| Repository file | Purpose |
| --- | --- |
| [00_create_db.sql](../db_mgmt/00_create_db.sql) | Creates the database if absent; requires an existing owner role. |
| [01_schema.sql](../db_mgmt/01_schema.sql) | Creates application schemas/tables and configures the role's database search path. |
| [02_sanity_check.sql](../db_mgmt/02_sanity_check.sql) | Checks all required tables and exercises simulator/parameter/result inserts inside a rolled-back transaction. |

The schema script contains additive, repeatable setup statements; it is not a
complete migration system or a substitute for backups. The sanity check leaves
no test rows, although PostgreSQL sequence counters can advance.

### Remote or managed PostgreSQL

The shell helpers target local PostgreSQL. For a remote server, use their SQL
files directly with `psql`. Create the login with your administrator account,
then create the database (the administrator must be allowed to do so):

```sh
psql 'host=postgres.example dbname=postgres user=postgres' -W \
  -v ON_ERROR_STOP=1 -v db_name=rtmf -v owner_role=rtmf \
  -f db_mgmt/00_create_db.sql
psql 'host=postgres.example dbname=rtmf user=rtmf' -W \
  -v ON_ERROR_STOP=1 -v db_name=rtmf -v owner_role=rtmf \
  -f db_mgmt/01_schema.sql
psql 'host=postgres.example dbname=rtmf user=rtmf' -W \
  -v ON_ERROR_STOP=1 -f db_mgmt/02_sanity_check.sql
```

Run from the repository/kit root. Apply the provider's TLS connection options
when required; see the [psql reference](https://www.postgresql.org/docs/current/app-psql.html).

### Allow application and compute connections

For a self-managed server, find its configuration paths:

```sh
sudo -u postgres psql -c 'SHOW config_file;' -c 'SHOW hba_file;'
```

Set `listen_addresses` in `postgresql.conf` to the database's reachable network
interface, or `'*'` when the host firewall/HBA rules restrict access. Add
`pg_hba.conf` entries for the actual application and compute source networks,
including Docker bridge/NAT addresses where applicable. For example:

```text
host  rtmf  rtmf  <APPLICATION_CIDR>  scram-sha-256
host  rtmf  rtmf  <COMPUTE_CIDR>      scram-sha-256
```

Use `hostssl` with configured server TLS when encrypted connections are required.
Restart the PostgreSQL instance after changing listening addresses; HBA-only
changes can be reloaded. Check first-match rule ordering in the
[PostgreSQL HBA reference](https://www.postgresql.org/docs/current/auth-pg-hba-conf.html).
For the distro service example:

```sh
sudo systemctl restart postgresql
psql 'host=postgres.example dbname=rtmf user=rtmf' -W \
  -c 'SELECT current_user, current_database();'
```

Repeat the connection check from application and compute networks. In the
framework bundle's `.env`, set both entries to this initialized database:

```dotenv
RTMF_JOBS_POSTGRES_DSN='postgresql://rtmf:CHANGE_ME@postgres.example:5432/rtmf'
RTMF_SIMULATORS_REPOSITORY_POSTGRES_DSN='postgresql://rtmf:CHANGE_ME@postgres.example:5432/rtmf'
```

Percent-encode reserved password characters and include your site's TLS options
in the URI. Certificate files referenced in a DSN must also exist in each
container/worker using that DSN.

## Object storage

### Install or obtain an S3 API

An existing S3-compatible service can be used directly. Obtain its API URL and
an administrative account for bucket/user creation. For AIStor, use its
[vendor installation guide](https://docs.min.io/aistor/). The MinIO Community
repository was archived on April 25, 2026. Its source-only distribution does
not provide maintained prebuilt community binaries; choose an approved storage
release and maintenance plan, and use a selected source revision rather than
assuming `minio/minio:latest` exists.
See the [MinIO source installation instructions](https://github.com/minio/minio/blob/master/README.md).

Example standalone MinIO installation, on the storage host with a Go toolchain
compatible with the chosen server/client source releases:

```sh
storage_build_dir="$(mktemp -d)"
GOBIN="$storage_build_dir" go install 'github.com/minio/minio@<MINIO_SOURCE_REF>'
GOBIN="$storage_build_dir" go install 'github.com/minio/mc@<MC_SOURCE_REF>'
sudo install -m 0755 "$storage_build_dir/minio" "$storage_build_dir/mc" /usr/local/bin/
sudo useradd --system --user-group --home-dir /srv/rtmf-minio --no-create-home --shell /usr/sbin/nologin minio
sudo install -d -o minio -g minio /srv/rtmf-minio
sudo install -m 0600 /dev/null /etc/rtmf-minio.env
```

The client can also be installed separately using its
[official installation instructions](https://github.com/minio/mc). Edit
`/etc/rtmf-minio.env`, setting a private administrator password:

```dotenv
MINIO_ROOT_USER=storage-admin
MINIO_ROOT_PASSWORD=<STRONG_STORAGE_ADMIN_PASSWORD>
```

Create `/etc/systemd/system/rtmf-minio.service`:

```ini
[Unit]
Description=RTMF object storage
Wants=network-online.target
After=network-online.target

[Service]
User=minio
Group=minio
EnvironmentFile=/etc/rtmf-minio.env
ExecStart=/usr/local/bin/minio server /srv/rtmf-minio --address :9000 --console-address :9001
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Start it and check the S3 API:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now rtmf-minio
curl --fail http://storage.example:9000/minio/health/live
```

This is a single-host HTTP example with persistent data under
`/srv/rtmf-minio`. Use your storage platform's deployment procedure for
replication, TLS, and backups.

### Create buckets and an application identity

From a machine with MinIO Client `mc`, add an admin alias. This client stores its
alias credentials locally; keep its configuration private. See
[mc alias set](https://docs.min.io/aistor/reference/cli/mc-alias/mc-alias-set/).

```bash
read -r -s -p 'Storage administrator password: ' storage_admin_secret
printf '\n'
mc alias set storage-admin http://storage.example:9000 storage-admin "$storage_admin_secret"
unset storage_admin_secret
mc mb --ignore-existing storage-admin/jobs-results
mc mb --ignore-existing storage-admin/tmp
mc mb --ignore-existing storage-admin/system-discovery
```

The buckets hold simulation results, parameter matrices, and frontend-managed
System Discovery archives respectively. Keep their names or update the
manifest's matching `resources.*_storage.bucket` values. See the
[bucket creation reference](https://docs.min.io/aistor/reference/cli/mc-mb/).

Save this as `rtmf-storage-policy.json` on the administration machine:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:*"],
    "Resource": [
      "arn:aws:s3:::jobs-results", "arn:aws:s3:::jobs-results/*",
      "arn:aws:s3:::tmp", "arn:aws:s3:::tmp/*",
      "arn:aws:s3:::system-discovery", "arn:aws:s3:::system-discovery/*"
    ]
  }]
}
```

Create a dedicated application user restricted to these buckets:

```bash
read -r -s -p 'New RTMF storage secret: ' storage_app_secret
printf '\n'
mc admin policy create storage-admin rtmf-buckets rtmf-storage-policy.json
mc admin user add storage-admin rtmf "$storage_app_secret"
mc admin policy attach storage-admin rtmf-buckets --user rtmf
mc alias set rtmf-storage http://storage.example:9000 rtmf "$storage_app_secret"
unset storage_app_secret
```

Use your provider's IAM equivalent for a non-MinIO S3 service. The MinIO
[identity and policy guide](https://docs.min.io/aistor/administration/multi-tenancy/)
describes user/policy association.

Verify using the **application** identity, not only the administrator:

```sh
printf 'RTMF storage check\n' | mc pipe rtmf-storage/tmp/infrastructure-check.txt
mc cat rtmf-storage/tmp/infrastructure-check.txt
mc rm rtmf-storage/tmp/infrastructure-check.txt
mc ls rtmf-storage/jobs-results
mc ls rtmf-storage/system-discovery
```

Set `resources.aistor.endpoint` to `storage.example:9000` without a scheme or
console path and `.secure` to `false` for this HTTP example (`true` for HTTPS).
Set `RTMF_AISTOR_ACCESS_KEY='rtmf'` and `RTMF_AISTOR_SECRET_KEY` to the new
application secret in the framework `.env`. Compute jobs need the same reachable
API and compatible worker-side TLS/credentials; a successful upload on the
application host alone does not prove compute-node access.

## Keycloak server

Skip installation if an existing Keycloak server is available. Obtain an admin
account, a stable public HTTPS address, and a persistent database. The example
uses a separate `keycloak` PostgreSQL database on the database host:

```sh
sudo -u postgres psql
```

```sql
CREATE ROLE keycloak LOGIN;
\password keycloak
CREATE DATABASE keycloak OWNER keycloak;
\q
```

Allow the identity host through PostgreSQL HBA/firewall rules, using database
and role `keycloak`. Do **not** apply `db_mgmt/01_schema.sql` to this database;
Keycloak manages its own schema.

On the identity host, create `/srv/rtmf-keycloak/compose.yaml`:

```yaml
name: rtmf-keycloak
services:
  keycloak:
    image: quay.io/keycloak/keycloak:${KEYCLOAK_VERSION:?Set a fixed Keycloak version}
    command: ["start"]
    env_file: ./keycloak.env
    ports: ["127.0.0.1:8080:8080"]
    restart: unless-stopped
```

In that directory's `.env`, set `KEYCLOAK_VERSION=<SELECTED_KEYCLOAK_VERSION>`.
Create a private `keycloak.env`:

```dotenv
KC_DB=postgres
KC_DB_URL=jdbc:postgresql://postgres.example:5432/keycloak
KC_DB_USERNAME=keycloak
KC_DB_PASSWORD=<KEYCLOAK_DATABASE_PASSWORD>
KC_HOSTNAME=https://identity.example
KC_HTTP_ENABLED=true
KC_PROXY_HEADERS=xforwarded
KC_BOOTSTRAP_ADMIN_USERNAME=bootstrap-admin
KC_BOOTSTRAP_ADMIN_PASSWORD=<TEMPORARY_ADMIN_PASSWORD>
```

Use the PostgreSQL connection/TLS options required by your site. Protect both
environment files, then start from `/srv/rtmf-keycloak`:

```sh
chmod 600 .env keycloak.env
docker compose config --quiet
docker compose up -d --pull missing
docker compose logs --tail 100 keycloak
```

This follows Keycloak's [standard container setup](https://www.keycloak.org/server/containers).
It uses `start` with persistent PostgreSQL. Configure the HTTPS reverse proxy
below before browser access; `KC_PROXY_HEADERS=xforwarded` assumes the trusted
proxy overwrites forwarded headers and the HTTP backend stays on loopback. See
[Keycloak reverse-proxy configuration](https://www.keycloak.org/server/reverseproxy).

Create your permanent administrator and remove the temporary bootstrap account
and bootstrap password configuration after initial setup. Then follow
[Keycloak application configuration](KEYCLOAK.md) to create the `rtmf` realm,
`rtmf-web` login client, `rtmf-use-case` permissions/audience, and first
user. These application resources are required in addition to starting Keycloak.

Verify discovery through the public URL:

```sh
curl --fail https://identity.example/realms/rtmf/.well-known/openid-configuration
```

Its `issuer` must equal the manifest's
`runtime.services.use_case.authentication.keycloak.issuer_url`. Set the login
client ID/secret and front callback URL as described in [Keycloak](KEYCLOAK.md).
Keycloak login tokens and Slurm JWTs are separate authentication paths.

## Simulator images and registry

### Install Harbor or use an existing OCI registry

The current simulator pipeline uses the registry's `/v2/` API and Basic
credentials for a manifest digest lookup. Harbor is the intended integration;
verify this lookup if choosing another OCI registry or authentication setup.
Application image pulls are separate and can use another registry.

For a new Harbor host, install Docker/Compose, download a fixed installer from
[Harbor's installation guide](https://goharbor.io/docs/main/install-config/),
verify the release archive, and unpack it. In its directory:

```sh
cp harbor.yml.tmpl harbor.yml
# Edit harbor.yml as described below.
sudo ./install.sh
```

Set `hostname` to the reachable registry DNS name, `data_volume` to persistent
storage, a private `harbor_admin_password`, and the installation's internal
database password. For the current simulator HTTP path, set `http.port` (the
example uses `5000`) and disable the `https` section. See the
[Harbor configuration reference](https://goharbor.io/docs/main/install-config/configure-yml-file/).

**Current compatibility constraint:** simulator image pushes request
`registry.http=true`, and submitted jobs run `apptainer --no-https`. A scheme-free
registry address also makes the repository's digest lookup use HTTP. An
HTTPS-only simulator registry requires integration changes; switching a JSON
hostname does not change these behaviors. Use the HTTP example only within the
site's controlled network. Application-image registries can use HTTPS normally.

In Harbor's administration interface:

1. Create project `base` for worker base images and `rtmf-simulators` for builds.
2. Create a repository-service account with pull access to `base` and pull/push
   access to `rtmf-simulators`.
3. Create a compute account with pull access to `rtmf-simulators`.
4. Record the exact generated usernames/secrets. Robot usernames can contain `$`;
   preserve them with single quotes in the framework `.env`.

Projects can be reused if their paths match the configured image names. See
[Harbor projects](https://goharbor.io/docs/main/working-with-projects/create-projects/)
and [robot accounts](https://goharbor.io/docs/main/administration/robot-accounts/).

Set under `runtime.services.simulators_repository.build_worker`:

```json
{
  "harbor_registry": "registry.example:5000",
  "harbor_project": "rtmf-simulators",
  "base_python_image_prefix": "base/worker-0.1.0-base-python"
}
```

These are **fields to edit in the existing object**, not a replacement for all
its other settings. Set `RTMF_HARBOR_USERNAME` / `RTMF_HARBOR_PASSWORD` to the
repository-service account, and `APPTAINER_DOCKER_USERNAME` /
`APPTAINER_DOCKER_PASSWORD` to the compute pull account.

If Docker is used to push bases to this HTTP registry, add its host/port to the
Docker daemon's existing `insecure-registries` list and restart Docker using the
site's procedure. Merge this with existing daemon configuration; it is not a
client `docker login` option. See [Harbor client setup](https://goharbor.io/docs/main/install-config/run-installer-script/).

### Worker base images are an additional prerequisite

For a registered Python `3.12` simulator, the prefix above resolves to:

```text
registry.example:5000/base/worker-0.1.0-base-python-312:latest
```

Verify the repository-service account can perform the digest lookup too. Once
this base exists, the following prompts for the account password:

```sh
curl --fail --head --user '<REPOSITORY_SERVICE_USERNAME>' \
  -H 'Accept: application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json' \
  http://registry.example:5000/v2/base/worker-0.1.0-base-python-312/manifests/latest
```

Expect HTTP 200 and a `Docker-Content-Digest` header. If the registry requires
a `WWW-Authenticate: Bearer` exchange, the current digest client does not
implement that exchange. It needs an integration update or an operator-provided
compatible endpoint, even if Docker/BuildKit login works. This follows the
[registry token-authentication flow](https://distribution.github.io/distribution/spec/auth/token/);
do not treat a successful image push alone as a successful registration check.

Python `3.11` uses suffix `-311`. The generator currently supports Linux/Python
simulators. The chosen image must match the compute architecture, provide
`/opt/simulator/.venv`, and run a compatible job executor as its inherited entry
point. The uploaded model must provide executable `/opt/simulator/start_sim.sh`,
the path used by the scheduler. Merely tagging an ordinary `python` image with
the base name is insufficient.

Obtain tested worker bases from the operator or maintain their build separately.
The source tree has older helper scripts under
`src/services/job_executor/docker/`, but they currently assume a service-local
`pyproject.toml`/source layout that is absent; the base Dockerfile also has an
old `composition.entrypoints.cli` module path. They need packaging updates before
use with this checkout. The current CLI module is
`services.job_executor.composition.entrypoints.cli`.

A compatible worker must load a `services.job_executor` runtime JSON section
through `RTMF_MAIN_CONFIGURATION_FILE`. Slurm currently forwards `MINIO_ENDPOINT`,
`MINIO_USER`, `MINIO_PASSWORD`, `POSTGRES_DSN`, and `JOB_EXECUTOR_USER` / `_GROUP`;
the worker's configuration must map those values, including the S3 TLS flag and
results bucket. The service renderer does not generate this worker configuration
or provision a tested worker release.

### BuildKit configuration

The simulator-repository Compose selection starts the pinned rootless BuildKit
sidecar automatically. It already includes its network, state volume, health
check, and a `buildctl` client in the application image. Keep
`build_worker.buildkit_addr` set to `tcp://buildkit:64000`.

For HTTP worker-base pulls, create `/srv/rtmf/buildkitd.toml` on the
simulator-repository host:

```toml
[registry."registry.example:5000"]
  http = true
```

Under `deployment.services.simulators_repository.compose.services.buildkit`,
set `command` to:

```json
["--addr", "tcp://0.0.0.0:64000", "--config", "/etc/buildkit/buildkitd.toml"]
```

Append this entry to its existing `volumes` list, keeping the state volume:

```json
{
  "type": "bind",
  "source": "/srv/rtmf/buildkitd.toml",
  "target": "/etc/buildkit/buildkitd.toml",
  "read_only": true,
  "bind": {"create_host_path": false}
}
```

The file must be readable by the BuildKit container's user. It is a host asset
that the renderer does not copy. See the
[BuildKit configuration reference](https://github.com/moby/buildkit/blob/master/docs/buildkitd.toml.md).
After application startup, verify the daemon:

```sh
docker compose exec buildkit buildctl --addr tcp://127.0.0.1:64000 debug workers
```

This checks the daemon; successful registration of a compatible sample
simulator checks base-image pulls, image building, pushing, and digest lookup.

## Slurm and compute nodes

### Install the cluster components

For a new cluster, use SchedMD's
[administrator installation guide](https://slurm.schedmd.com/quickstart_admin.html)
to install a single compatible Slurm release across the controller, compute
nodes, REST host, and client host. Packages/builds must include REST and JWT
support; installing only the `scontrol` client is insufficient. Configure:

- `slurmctld` on the controller with the site's nodes and partitions.
- `slurmd` on each compute node and matching `slurm.conf` topology.
- Munge daemons sharing the cluster's Munge key on authentication hosts.
- Consistent user IDs/groups, clocks, and cluster network access.
- Optional `slurmdbd` plus its own MariaDB/MySQL accounting store if the site uses accounting.

The framework calls `/slurm/<version>/...` controller APIs and stores its own
job records in PostgreSQL. It does not create Slurm users, partitions, account
associations, Munge keys, or accounting databases. For an existing cluster,
have its administrator provide the submit identity, partition, and REST access.

Before adding RTMF, verify as the intended submit account:

```sh
scontrol ping
sinfo
sbatch --wait --wrap='hostname'
```

Supply the site's partition/account options if required. These checks should
work independently of the application.

### Enable REST/JWT authentication

The installed Slurm build must include JWT support. Configure a private signing
key on the controller and, if used, the accounting daemon host. In their
`slurm.conf` / `slurmdbd.conf`, enable the alternative JWT authentication path:

```text
AuthAltTypes=auth/jwt
AuthAltParameters=jwt_key=/var/spool/slurm/statesave/jwt_hs256.key
```

For a **new** signing-key setup, on the controller (replace the Slurm service
account/path if different):

```sh
sudo install -d -o slurm -g slurm -m 0755 /var/spool/slurm/statesave
sudo -u slurm sh -c 'umask 077; openssl rand 32 > /var/spool/slurm/statesave/jwt_hs256.key'
```

Reuse an existing key rather than regenerating it. Supply the same protected
key to `slurmdbd` if used, and configure the actual path on each host. Keep the
site's existing Munge authentication. Restart affected daemons following the
site's maintenance procedure. See
[Slurm JWT setup](https://slurm.schedmd.com/jwt.html).

Run `slurmrestd` as its own unprivileged service account, with
`SLURM_JWT=daemon` and authentication plugin `rest_auth/jwt`. Configure its
listening address/port (example `6820`) and enable REST/data-parser plugins for
the cluster release. Inspect available plugins with:

```sh
slurmrestd -a list
slurmrestd -s list
```

Configure the site's `slurmrestd` systemd unit to apply those options; package
unit paths and default listeners vary. See the
[slurmrestd reference](https://slurm.schedmd.com/slurmrestd.html) and
[REST setup](https://slurm.schedmd.com/rest.html).

Set `runtime.services.jobs_scheduler.slurm.base_url` to
`http://slurm.example:6820` and `.api_version` to a version the daemon actually
serves. The template's `v0.0.43` is an example, not a version enabled by every
Slurm package. Enable the matching endpoint/data parser before using it.

### Prepare the scheduler application's host

Install client binaries and libraries compatible with that cluster, plus a
working Munge daemon/socket in its authentication domain. The template mounts:

```text
/usr/bin/scontrol
/etc/slurm
/usr/lib/x86_64-linux-gnu/slurm
/lib/x86_64-linux-gnu/libmunge.so.2
/run/munge
/tmp/workspace
```

Adjust source/target paths under
`deployment.services.jobs_scheduler.compose.services.jobs_scheduler.volumes`.
The library paths are Debian-style examples. Check `ldd /usr/bin/scontrol` and
ensure the mounted executable's dependencies exist in the container. Mount the
Munge socket, not the cluster's private JWT signing key.

The scheduler container defaults to application UID/GID `1013` and a Slurm
account UID/GID `995`. Match the submit user's numeric identity and any required
socket group access. Rebuild with `RTMF_UID`, `RTMF_GID`, `SLURM_UID`, and
`SLURM_GID` when necessary; see [image building](IMAGES.md#build-locally-with-docker).

Set `SLURM_USER_NAME` to the identity represented by the generated token.
The current client runs `scontrol token lifespan=900` as the container process;
it does not use that variable to change UID or request a different username.
The resulting JWT identity and the configured REST username must agree.
`JOB_EXECUTOR_USER` / `_GROUP` configure values passed to the worker/simulator;
they do not grant Slurm permissions or change the scheduler container's UID.

### Install Apptainer and prepare compute paths

Install Apptainer on every compute node. For Ubuntu, the official package
recipe is:

```sh
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:apptainer/ppa
sudo apt update
sudo apt install -y apptainer
apptainer --version
```

Use the [Apptainer installation guide](https://apptainer.org/docs/admin/main/installation.html)
for your distribution and user-namespace/setuid requirements. Ensure `apptainer`
is on the noninteractive batch job's `PATH`; loading an interactive login-shell
module alone is insufficient.

Provide a writable work directory shared between compute nodes and the
scheduler host when the application needs to read job logs. For example, create
`/shared/rtmf` owned by the submit user. Set these scheduler Slurm fields:

```json
{
  "working_directory": "/shared/rtmf",
  "stdout": "/shared/rtmf/%A_%a.out",
  "stderr": "/shared/rtmf/%A_%a.err"
}
```

Mount `/shared/rtmf` at the same path in the scheduler container, replacing
the template's workspace mount. The root directory must exist before job
submission. Flat log filenames avoid relying on per-job directories that the
job script creates only after Slurm opens its output files.

As the submit user on a compute node, test a **known existing** compatible base:

```sh
apptainer exec --no-https --docker-login \
  docker://registry.example:5000/base/worker-0.1.0-base-python-312:latest \
  /opt/simulator/.venv/bin/python --version
```

Use the compute pull account. Also verify access from that node to S3 and
PostgreSQL using the application identity. Match the image architecture,
registry address, executor configuration, and TLS settings to those jobs use.

### Verify authentication inside the application container

After rendering and starting the scheduler bundle, run from its Compose
directory. This uses the same token-generation and header path as the adapter
without printing the JWT:

```sh
docker compose exec -T jobs_scheduler python - <<'PY'
import json
import os
import subprocess
import urllib.request
config = json.load(open(os.environ['RTMF_MAIN_CONFIGURATION_FILE']))
slurm = config['services']['jobs_scheduler']['slurm']
result = subprocess.run(['scontrol', 'token', 'lifespan=60'], check=True, capture_output=True, text=True)
token = next(line.split('=', 1)[1].strip() for line in result.stdout.splitlines() if line.startswith('SLURM_JWT='))
url = slurm['base_url'].rstrip('/') + '/slurm/' + slurm['api_version'] + '/jobs'
request = urllib.request.Request(url, headers={
    'X-SLURM-USER-NAME': os.environ['SLURM_USER_NAME'],
    'X-SLURM-USER-TOKEN': token,
})
with urllib.request.urlopen(request, timeout=10) as response:
    data = json.load(response)
    if data.get('errors'):
        raise SystemExit('Slurm returned API errors; inspect cluster logs')
    print('Authenticated Slurm jobs request: OK')
PY
```

An HTTP 200 from RTMF's `/health` alone does not prove this integration.

## Public HTTPS access

Provide public DNS and certificates for `rtmf.example` and
`identity.example`. Obtain certificates through your site's CA/ACME process
before installing these server blocks. On an Ubuntu/Debian proxy host:

```sh
sudo apt install -y nginx
```

Example `/etc/nginx/conf.d/rtmf.conf`, when the proxy shares the frontend
and Keycloak Docker host:

```nginx
server {
    listen 443 ssl;
    server_name rtmf.example;
    ssl_certificate /etc/letsencrypt/live/rtmf.example/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/rtmf.example/privkey.pem;
    client_max_body_size 100m;
    location / {
        proxy_pass http://127.0.0.1:63000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
server {
    listen 443 ssl;
    server_name identity.example;
    ssl_certificate /etc/letsencrypt/live/identity.example/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/identity.example/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

If these services are on different hosts, install each block on the respective
host or use private reachable upstream addresses instead of loopback. Adjust
certificate paths and the simulator-upload limit for your installation. Validate
and reload:

```sh
sudo nginx -t
sudo systemctl reload nginx
```

See the [Nginx proxy reference](https://nginx.org/en/docs/http/ngx_http_proxy_module.html).
The frontend URL, Keycloak valid redirect URI, and manifest callback URL must
agree (`https://rtmf.example/auth/callback` in this example).

## Handoff to application deployment

Before starting the complete application, confirm:

- PostgreSQL sanity checks pass and both application DSNs target the initialized database.
- The application S3 identity can upload, read, list, and delete in the configured buckets.
- Keycloak discovery uses the public issuer URL; realm/client/roles/user setup is complete.
- Worker bases exist and can be pulled on compute nodes; the repository account can build/push and look up simulator manifests.
- Slurm submission works as the configured account, REST authentication works, and compute work/log paths are available.
- DNS and HTTPS certificates work from browsers, application containers, and the relevant cluster nodes.

Fill the matching manifest fields and `.env` values, then follow the ordered
[application startup commands](DEPLOYMENT.md#full-framework-or-selected-services).
After startup, register an operator-provided compatible sample simulator,
submit a small job, and retrieve its results to verify the complete path.
