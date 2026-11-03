# Deploy RTMF

Prepare configuration with the repository's scripts, then use Docker Compose
for startup and normal operations. Rendering creates one **bundle** containing
`compose.yaml` and runtime JSON for the services installed on a machine.

Choose a path:

- [Single-server VM setup](SINGLE_SERVER_VM.md): provision an isolated VM, restrict its network access, and prepare local or external dependencies before application deployment.
- [Parser first run](#parser-first-run): build and start one independent service.
- [Full framework or selected services](#full-framework-or-selected-services): configure an installation and start it.
- [Multiple machines](#multiple-machines): keep remote backends on their own hosts.
- [Prepared bundle](#start-a-prepared-bundle): start files already configured by an operator.

## Requirements and checkout

Use a Linux host with Docker Engine, the Compose plugin, Python 3.11+, Git,
`curl`, and a Bash-compatible shell. Host Python needs no application packages.
Check the tools, then obtain the source:

```sh
docker version
docker compose version
python3 --version
git clone '<PUBLIC_REPOSITORY_URL>' rtmf-server
cd rtmf-server
```

Docker must report both a client and a running server. Replace all `<...>`
release placeholders with the publisher's values and `.example` addresses with
real installation addresses. The default `rtmf/<image>:latest` names do not
identify an existing public release. If you received a deployment **kit**, start
at step 1 below and use published images; a kit has no source or Dockerfiles.

## Parser first run

From a full source checkout, run these commands in order. This starts the
parser API without PostgreSQL, storage, Keycloak, or Slurm:

```sh
docker build -f docker/parser/Dockerfile -t rtmf/parser:local .
./scripts/init_deployment.sh
./scripts/render_deployment.py --check-env --image rtmf/parser:local parser
cd dist/deployment
docker compose config --quiet
docker compose up -d --pull missing
docker compose ps -a
curl --fail --retry 15 --retry-connrefused --retry-delay 2 http://localhost:63700/openapi.json
```

Expect JSON with title `RTMF Parser Service`. Open
[the API documentation](http://localhost:63700/docs). This is one API, not the
complete web application. To stop it and return to the repository root:

```sh
docker compose down
cd ../..
```

## Full framework or selected services

Run steps 1–5 in order. For a partial installation, configure only the resources
and credentials used by your selected services and their workflows.

### 1. Initialize configuration

From the repository or deployment-kit root:

```sh
./scripts/init_deployment.sh
```

This creates `config/deployment.json` (the editable **manifest**) and
`dist/deployment/.env` (private credentials), preserving existing files.

### 2. Prepare images and infrastructure; edit the manifest

Obtain the application's image namespace and a fixed release tag from the
publisher. If its registry requires an account, run:

```sh
docker login '<APP_REGISTRY_HOST>'
```

Alternatively, [build application images locally](IMAGES.md#build-locally-with-docker).
That recipe uses namespace `rtmf` and tag `local` and supports selected
services. Rendering does not build images.

Prepare the [external infrastructure](INFRASTRUCTURE.md) required by this
installation. For front, also complete [Keycloak setup](KEYCLOAK.md), including
a user with application roles. Compose starts application containers and
BuildKit; it does not provision those external systems or worker base images.

Edit these paths in `config/deployment.json` as applicable:

| JSON path | Set to |
| --- | --- |
| `deployment.images.repository`, `.tag` | `<APP_IMAGE_NAMESPACE>` and `<RELEASE_TAG>`, or `rtmf` and `local` for local builds. |
| `resources.aistor.endpoint`, `.secure` | Reachable S3 API host/port and its HTTPS boolean. |
| `runtime.services.front.authentication.callback_url` | Public HTTPS frontend URL plus `/auth/callback`. |
| `runtime.services.use_case.authentication.keycloak.issuer_url`, `.client_id` | Keycloak realm URL and login client, normally `rtmf-web`. |
| `runtime.services.jobs_scheduler.slurm.base_url`, `.api_version` | Slurm REST URL and a version enabled on the cluster. |
| `deployment.services.jobs_scheduler.compose.services.jobs_scheduler.volumes` | Actual Slurm/Munge and workspace paths on the scheduler host. |
| `runtime.services.simulators_repository.build_worker.harbor_registry`, `.harbor_project` | Simulator-image registry host/port without a scheme, and project name. |
| `runtime.services.simulators_repository.build_worker.base_python_image_prefix` | Compatible worker base-image prefix supplied by the operator. |
| `endpoints.<name>.base_url` | Real addresses of backends installed on other machines. |

See [Configuration](CONFIGURATION.md) for references and advanced overrides.
Keep `deployment.local_endpoints` set to `true`: references to services selected
for this bundle use Docker DNS automatically. References to absent services keep
their configured remote URLs. Container `localhost` points to that container.
The included BuildKit sidecar uses `tcp://buildkit:64000`; keep that address.

Backend publication hosts default to `127.0.0.1`. For a single-host installation
with a host reverse proxy, also set front's
`deployment.services.front.publish.host` to `127.0.0.1` and forward public HTTPS
traffic to front's host port `63000`. For backends called by other machines,
publish on an internal interface and configure those clients' URLs. The operator
must ensure that backend addresses and ports are reachable only from the
internal network, including when changing a port; these APIs rely on the
network boundary for access control.

### 3. Fill credentials

Edit `dist/deployment/.env`. Required variables depend on the services you
select; unrelated entries can stay blank:

| Variables | Meaning |
| --- | --- |
| `RTMF_AISTOR_ACCESS_KEY`, `RTMF_AISTOR_SECRET_KEY` | S3 bucket credentials. |
| `RTMF_JOBS_POSTGRES_DSN`, `RTMF_SIMULATORS_REPOSITORY_POSTGRES_DSN` | PostgreSQL URIs; use the same initialized database for the documented setup. |
| `RTMF_KEYCLOAK_CLIENT_SECRET` | Login client's Keycloak secret. |
| `RTMF_SECRET_KEY`, `RTMF_SESSION_TOKEN_PEPPER`, `RTMF_KEYCLOAK_TOKEN_ENCRYPTION_KEY` | Generate separate application secrets below; needed by front. |
| `SLURM_USER_NAME` | Cluster submit account. |
| `JOB_EXECUTOR_USER`, `JOB_EXECUTOR_GROUP` | Compute execution identity agreed with the cluster operator. |
| `APPTAINER_DOCKER_USERNAME`, `APPTAINER_DOCKER_PASSWORD` | Credentials to pull simulator images on compute nodes. |
| `RTMF_HARBOR_USERNAME`, `RTMF_HARBOR_PASSWORD` | Credentials to push simulator images. |

For front, generate three values and copy them into their `.env` entries:

```sh
python3 - <<'PY'
import base64
import secrets
print('RTMF_SECRET_KEY=' + secrets.token_hex(32))
print('RTMF_SESSION_TOKEN_PEPPER=' + secrets.token_hex(32))
print('RTMF_KEYCLOAK_TOKEN_ENCRYPTION_KEY=' + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
PY
```

Example database entries, replacing the user/password/host:

```dotenv
RTMF_JOBS_POSTGRES_DSN='postgresql://rtmf:CHANGE_ME@postgres.example:5432/rtmf'
RTMF_SIMULATORS_REPOSITORY_POSTGRES_DSN='postgresql://rtmf:CHANGE_ME@postgres.example:5432/rtmf'
```

Percent-encode reserved characters in URI credentials. Use single-quoted literal
`.env` values, especially for `$`, `#`, or spaces. Keep the file private; shell
variables override it. Optional client tokens can stay commented out unless
remote services require them.

### 4. Render the services installed here

From the repository/kit root, run **one** of these commands:

| Installation | Command |
| --- | --- |
| Full framework: all nine application services | `./scripts/render_deployment.py --check-env` |
| Frontend using remote backends | `./scripts/render_deployment.py --check-env front` |
| Simulator repository and its BuildKit sidecar | `./scripts/render_deployment.py --check-env simulators_repository` |
| Analytics and parser | `./scripts/render_deployment.py --check-env analytics parser` |
| Frontend with local analytics; other backends remote | `./scripts/render_deployment.py --check-env front analytics` |
| Independent APIs without external infrastructure | `./scripts/render_deployment.py --check-env visualization parser system_discovery` |

Pass any combination of service names after `--check-env`. Only that combination
is installed. The command validates required environment values and writes the
bundle while preserving `.env`. Its `.env.example` and `environment.json` list
the selected services' required/optional variables. To validate without writing,
add `--check` to the same command.

### 5. Start the bundle

After **any** selection in step 4, run:

```sh
cd dist/deployment
docker compose config --quiet
docker compose up -d --pull missing
docker compose ps -a
```

The same sequence works with published images and images already built/loaded
locally. `--pull missing` downloads only missing images, including BuildKit when
selected. For fixed tags already present, fetch updates explicitly; see [Updates](#updates).
See Docker's [Compose startup reference](https://docs.docker.com/reference/cli/docker/compose/up/).

Expect the selected application containers to stay running. With the full
selection, there are nine application containers and one healthy BuildKit
sidecar. No service-by-service startup order is required. Compose waits for
BuildKit before starting the simulator repository. A repeating restart is a
failure; inspect it with `docker compose logs --tail 100 <service>`.

## Services and ports

Host ports below come from the public template; container applications listen
on `8000`. These are also the names accepted by the renderer and Compose.

| Service | Host port | Resources needed by its workflows |
| --- | ---: | --- |
| `front` | 63000 | Keycloak, PostgreSQL, S3, and the local/remote backend APIs used by the UI. Includes use-case orchestration. |
| `analytics` | 63100 | S3 simulation results. |
| `jobs_scheduler` | 63200 | PostgreSQL, S3, Slurm, and compute-node access to simulator images. |
| `matrix_generation` | 63300 | S3 matrix storage. |
| `simulators_repository` | 63400 | PostgreSQL, simulator registry, worker bases, and the automatic BuildKit sidecar. |
| `visualization` | 63500 | No external infrastructure for the standalone API. |
| `evaluator` | 63600 | PostgreSQL, S3, and scheduler/repository/analytics/parser/matrix APIs. |
| `parser` | 63700 | No external infrastructure. |
| `system_discovery` | 63800 | No external infrastructure for the standalone API; uses local working files. |

Selecting a service does not automatically install the other HTTP APIs it calls.
Provide those APIs locally in the same bundle or set reachable remote endpoints.
Frontend-only deployment therefore needs working remote backends for their UI
features. `use_case` runs inside front; `job_executor` is not a persistent Compose
service in this repository.

## Verify the installation

Run checks for services included in your installation. For the full framework,
from the application host:

```sh
curl --fail --retry 15 --retry-connrefused --retry-delay 2 http://127.0.0.1:63700/openapi.json
curl --fail http://127.0.0.1:63200/health
curl --head https://rtmf.example/auth/login
```

Expect parser OpenAPI JSON, HTTP 200 from scheduler health, and a login redirect
to Keycloak. Open the public frontend URL and sign in with your configured
Keycloak user; there is no built-in administrator password.

For a complete simulation check, use an operator-provided compatible simulator:
register it, wait for its image build, submit a small simulation, and open its
results. Health checks alone do not verify Slurm submission or storage access.
This repository does not ship a complete sample cluster or worker base-image
release.

## Multiple machines

Repeat steps 1–5 on each host, selecting exactly the services installed there.
Set each host's remote `endpoints.*.base_url` values before rendering. A service
published only on `127.0.0.1` is not reachable from other hosts.
Publish remote backends on an internal interface and restrict their ports to
the internal network with the host firewall or equivalent network rules.

For a separate front bundle in a custom directory, from the repository root:

```sh
./scripts/init_deployment.sh --output-dir dist/front
# Edit config/deployment.json for this host and fill dist/front/.env.
./scripts/render_deployment.py --check-env --output-dir dist/front --project-name rtmf-front front
cd dist/front
docker compose config --quiet
docker compose up -d --pull missing
docker compose ps -a
```

Keep initializer and renderer output paths identical so validation and Compose
read the same `.env`. Use different project names if bundles share a Docker
host. The source manifest must describe the intended host before each render.

## Start a prepared bundle

If an operator supplies a rendered directory, only Docker/Compose is required.
Enter the directory containing `compose.yaml`, then:

```sh
test -f .env || cp .env.example .env
# Fill .env with this installation's credentials before continuing.
docker compose config --quiet
docker compose up -d --pull missing
docker compose ps -a
```

Host mount paths, endpoint settings, and external resources must already match
this host. Follow the bundle's README for its exact service list and images.

## Daily operations

Run from the directory containing `compose.yaml`:

```sh
docker compose logs -f front
docker compose stop front
docker compose up -d --pull missing front
docker compose up -d --pull missing simulators_repository
docker compose down
```

Use names included in your bundle. `up front` starts front; it does not rewrite
its client URLs or start HTTP backends. In a full bundle those URLs still point
to local containers, so the backends must be running. To deploy front against
remote backends, render a front-only bundle. `down` stops/removes the whole
machine's Compose application.

## Updates

From the repository root, edit the manifest and set the new published image
tag if needed. Render with the **same service selection and output/project
options** used for this installation. For the full default bundle:

```sh
./scripts/render_deployment.py --check-env
cd dist/deployment
docker compose pull
docker compose up -d --remove-orphans
docker compose ps -a
```

For local builds, rebuild the changed images and use
`docker compose up -d --pull never --remove-orphans` instead of `pull` and `up`
above. Keep any required sidecar image present. Re-rendering changes a
configuration hash so Compose recreates containers whose JSON changed.

Back up external PostgreSQL/S3 data separately. BuildKit keeps a named state
volume. Parser/System Discovery working files are container-local unless you
add mounts, so recreation loses them. Frontend sessions reset on restart.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Image pull fails | Published namespace/tag, registry login, and whether a local image was built. |
| Missing/empty required environment values | Fill the named `.env` entries and check overriding shell variables. |
| Bind source does not exist | Prepare scheduler/BuildKit host assets or correct their manifest paths. |
| Database schema errors | Initialize the shared database with `db_mgmt/01_schema.sql`. |
| S3 access/bucket errors | API address, HTTPS flag, bucket names, and access credentials. |
| Login fails, loops, or returns `403` | Public HTTPS URL, exact Keycloak callback, client secret, audience, and roles. |
| Simulator image build fails | Compatible worker bases, registry credentials, and the documented HTTP registry requirement. |
| Slurm authentication fails or REST returns `404` | Submit identity, UID/GID, Munge/client mounts, and cluster-supported API version. |
