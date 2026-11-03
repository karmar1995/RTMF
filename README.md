# RTMF (Resiliency Through Multisimulation Framework)

RTMF registers simulation models, runs simulation batches on a Slurm
cluster, and analyses their results. It also supports evaluation and
system-identification workflows.

**Distributed deployment is covered under `docs/`:** see
[Deployment: multiple machines](docs/DEPLOYMENT.md#multiple-machines),
[Configuration](docs/CONFIGURATION.md), and
[Third-party infrastructure](docs/INFRASTRUCTURE.md). The instructions below
cover a single application server.

## Single-server deployment

Deploy the complete RTMF application in a dedicated, isolated Linux virtual
machine (VM). All nine application services and the simulator repository's
BuildKit sidecar run inside that VM in one Docker Compose project. The frontend
includes the use-case layer.

The framework VM must have access to a separately deployed Slurm cluster,
including its REST endpoint and the client/Munge integration described below.
Slurm controller and compute services run outside the framework VM. Compute
nodes must also be able to reach the framework's database, object storage,
and simulator-image registry.

Keycloak is required for frontend login. It may run alongside the framework
inside the VM or be deployed separately, with its HTTPS issuer URL reachable
from both the framework VM and users' browsers. PostgreSQL, S3/MinIO, and the
simulator-image registry may also run alongside the application or use existing
services. Configure these dependencies before starting the complete framework.
Compose starts the application and BuildKit. Before the application steps,
follow [Single-server VM setup](docs/SINGLE_SERVER_VM.md) to provision the VM,
apply network isolation, and install or connect its dependencies. Detailed
service installation recipes are in
[Third-party infrastructure](docs/INFRASTRUCTURE.md).

Follow steps 1–6 in order. Replace `<...>` placeholders with your release values
and `.example` addresses with reachable installation addresses. Public repository
and image release locations are placeholders until a release is published.

### 1. Check the server and obtain the source

Provision the isolated Linux VM with Docker Engine, its Compose plugin,
Python 3.11+, Git, `curl`, and Bash. Dependency checks below also use PostgreSQL client `psql`,
MinIO Client `mc`, and compatible Slurm client tools. Apptainer runs on the
compute nodes.

```sh
docker version
docker compose version
python3 --version
git clone '<PUBLIC_REPOSITORY_URL>' rtmf-server
cd rtmf-server
```

Docker must report both a client and a running server. Run subsequent application
commands from this checkout unless another directory/host is specified. Host
Python needs no application packages.

### 2. Prepare and validate third-party systems

Complete the [infrastructure setup](docs/INFRASTRUCTURE.md) and
[Keycloak realm/client/user setup](docs/KEYCLOAK.md) first. Validate using the
accounts and network paths the framework will use, including compute-node
access to PostgreSQL, storage, and simulator images. Resolve any failed check
before continuing to application startup.

**PostgreSQL.** Create the application role/database and initialize its schema
using the [ordered `db_mgmt` setup](docs/INFRASTRUCTURE.md#create-the-account-then-use-db_mgmt).
Use one initialized application database for both framework DSNs. From the
application server, verify it with the application account:

```sh
psql 'host=postgres.example dbname=rtmf user=rtmf' -W \
  -v ON_ERROR_STOP=1 -f db_mgmt/02_sanity_check.sql
```

Expect `Sanity check finished OK`. This checks required tables and exercises
inserts in a rolled-back transaction. Add your site's PostgreSQL TLS options.
Repeat the connection check from compute nodes. Keycloak uses its own separate
database, initialized by Keycloak.

**S3/MinIO.** Create buckets `jobs-results`, `tmp`, and `system-discovery` and a
bucket-scoped application identity as described in
[Object storage](docs/INFRASTRUCTURE.md#object-storage). Test that identity,
rather than the storage administrator:

```bash
read -r -s -p 'RTMF storage secret: ' storage_app_secret
printf '\n'
mc alias set rtmf-storage http://storage.example:9000 rtmf "$storage_app_secret"
unset storage_app_secret
storage_probe_key="deployment-check-$(python3 -c 'import uuid; print(uuid.uuid4())').txt"
for bucket in jobs-results tmp system-discovery; do
  printf 'RTMF storage check\n' | mc pipe "rtmf-storage/$bucket/$storage_probe_key"
  mc cat "rtmf-storage/$bucket/$storage_probe_key"
  mc ls "rtmf-storage/$bucket"
  mc rm "rtmf-storage/$bucket/$storage_probe_key"
done
```

Every upload/read/list/delete must succeed. Use the real API URL and access-key
name; use HTTPS if configured. `mc` keeps alias credentials locally. Compute
workers must also reach this API with their configured credentials/TLS settings.

**Keycloak and HTTPS.** Use Keycloak hosted inside the framework VM or a
separately deployed identity service. Configure public DNS, certificates, the
login client, its exact callback URI, permissions/audience, and the first user. Verify realm
discovery through the same HTTPS URL browsers and front will use:

```sh
curl --fail https://identity.example/realms/rtmf/.well-known/openid-configuration
```

Confirm the returned `issuer` is `https://identity.example/realms/rtmf`
with your real hostname. Configure the callback as
`https://rtmf.example/auth/callback`. Follow
[Public HTTPS access](docs/INFRASTRUCTURE.md#public-https-access) to route the
frontend to host port `63000` and, if hosted here, Keycloak to its backend port.
If using Nginx, validate its installed configuration on the proxy host:

```sh
sudo nginx -t
```

**Simulator registry and worker bases.** Prepare the registry projects,
repository push/pull account, compute pull account, and compatible worker bases.
See [Simulator images and registry](docs/INFRASTRUCTURE.md#simulator-images-and-registry),
including the current HTTP-registry and digest-authentication requirements and
the status of older worker build helpers. The application images do not supply
these worker bases.

For an existing Python 3.12 base matching the example configuration, check the
repository account's manifest access; `curl` prompts for its password:

```sh
curl --fail --head --user '<REPOSITORY_SERVICE_USERNAME>' \
  -H 'Accept: application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json' \
  http://registry.example:5000/v2/base/worker-0.1.0-base-python-312/manifests/latest
```

Expect HTTP 200 and `Docker-Content-Digest`. Adapt the path to the actual base.
A registry requiring a Bearer-token exchange needs the integration described in
the infrastructure guide; successful Docker login alone does not validate the
current manifest lookup.

**Slurm, Munge, and Apptainer.** Complete
[Slurm setup](docs/INFRASTRUCTURE.md#slurm-and-compute-nodes), including REST/JWT
support, submit-user identity, scheduler-host client/Munge mounts, and a writable
compute work directory. On the application server, as the intended submit user:

```sh
scontrol ping
sinfo
sbatch --wait --wrap='hostname'
```

Expect a responding controller, an available partition, and a successful test
job. Supply site-specific partition/account options when required. On a compute
node, verify Apptainer and a known compatible base using an account with pull
access to that base:

```sh
apptainer --version
apptainer exec --no-https --docker-login \
  docker://registry.example:5000/base/worker-0.1.0-base-python-312:latest \
  /opt/simulator/.venv/bin/python --version
```

Expect the base's Python version. The job's pull account must also be able to
pull built images from the simulator project. Slurm REST authentication from
inside the scheduler container is checked after application startup in step 6.

### 3. Obtain application images and initialize configuration

Choose published images and their fixed release tag, or build all application
images from this checkout:

```bash
for service in front analytics jobs_scheduler matrix_generation simulators_repository visualization evaluator parser system_discovery; do
  image_name="${service//_/-}"
  docker build -f "docker/$service/Dockerfile" -t "rtmf/$image_name:local" .
done
```

For this local build, use image repository `rtmf` and tag `local`. If using
private published images, run `docker login '<APP_REGISTRY_HOST>'` instead of
the build loop. Scheduler UID/GID build arguments may need site-specific values;
see [Images](docs/IMAGES.md#build-locally-with-docker).

Initialize the two editable deployment inputs:

```sh
./scripts/init_deployment.sh
```

This creates `config/deployment.json` and `dist/deployment/.env`, preserving
existing files.

### 4. Configure this server

Edit `config/deployment.json`:

| Setting | Value |
| --- | --- |
| `deployment.images.repository`, `.tag` | `rtmf` / `local` for the build above, or the published namespace/tag. |
| `deployment.services` | Keep all nine application services for this recipe. |
| `deployment.local_endpoints` | Keep `true`; selected services communicate over Docker DNS. |
| `deployment.services.<name>.publish.host` | Backends default to `127.0.0.1`; use it for front too when the reverse proxy runs on this host. |
| `resources.aistor.endpoint`, `.secure` | S3 API host/port without a scheme, and its HTTPS boolean. |
| `runtime.services.front.authentication.callback_url` | Public frontend HTTPS URL plus `/auth/callback`. |
| `runtime.services.use_case.authentication.keycloak.issuer_url`, `.client_id` | Validated realm URL and login client, normally `rtmf-web`. |
| `runtime.services.jobs_scheduler.slurm` | Slurm REST URL/API version, partition, work directory, and output/error paths matching the cluster. |
| `deployment.services.jobs_scheduler.compose.services.jobs_scheduler.volumes` | Existing, compatible Slurm/Munge client files and the work/log directory. |
| `runtime.services.simulators_repository.build_worker` | Simulator registry/project and compatible worker base prefixes. Keep `buildkit_addr` as `tcp://buildkit:64000`. |

If you change a backend's publication address or port for access from another
machine, ensure it is reachable only from the internal network. See
[multiple-machine deployment](docs/DEPLOYMENT.md#multiple-machines).

Apply the [BuildKit HTTP registry configuration](docs/INFRASTRUCTURE.md#buildkit-configuration)
when using the simulator-registry example. Host files referenced by Compose
must exist. All selected application-to-application endpoints are derived
locally; the infrastructure addresses must still be reachable from containers.

Fill `dist/deployment/.env` using the validated accounts:

| Variables | Values |
| --- | --- |
| `RTMF_JOBS_POSTGRES_DSN`, `RTMF_SIMULATORS_REPOSITORY_POSTGRES_DSN` | URIs for the same initialized application database. |
| `RTMF_AISTOR_ACCESS_KEY`, `RTMF_AISTOR_SECRET_KEY` | Application S3 identity. |
| `RTMF_KEYCLOAK_CLIENT_SECRET` | Keycloak login client's secret. |
| `RTMF_SECRET_KEY`, `RTMF_SESSION_TOKEN_PEPPER`, `RTMF_KEYCLOAK_TOKEN_ENCRYPTION_KEY` | Three separate generated application secrets. |
| `SLURM_USER_NAME` | Slurm identity represented by the scheduler container's generated token. |
| `JOB_EXECUTOR_USER`, `JOB_EXECUTOR_GROUP` | Worker/simulator identity settings agreed with the operator. |
| `RTMF_HARBOR_USERNAME`, `RTMF_HARBOR_PASSWORD` | Simulator repository's registry account. |
| `APPTAINER_DOCKER_USERNAME`, `APPTAINER_DOCKER_PASSWORD` | Compute pull account. |

Generate the three application secrets and copy their values into `.env`:

```sh
python3 - <<'PY'
import base64
import secrets
print('RTMF_SECRET_KEY=' + secrets.token_hex(32))
print('RTMF_SESSION_TOKEN_PEPPER=' + secrets.token_hex(32))
print('RTMF_KEYCLOAK_TOKEN_ENCRYPTION_KEY=' + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
PY
```

Use simple single-quoted literal `.env` entries such as `NAME='value'`. Keep the
file private. Percent-encode reserved characters in database URI credentials;
shell environment values override `.env`. Optional client-token entries can stay
commented out for the default local backend setup. See
[Configuration](docs/CONFIGURATION.md) for the full format.

### 5. Render and start the complete application

From the checkout root, run in order:

```sh
./scripts/render_deployment.py --check-env
cd dist/deployment
docker compose config --quiet
docker compose up -d --pull missing
docker compose ps -a
```

The renderer validates required environment values and generates the Compose
bundle, preserving `.env`. Startup uses existing local images and downloads
missing images, including the BuildKit sidecar. No per-service startup order is
needed; Compose waits for healthy BuildKit before starting the repository.

Expect all nine application containers to remain running and BuildKit to become
healthy. Inspect failures before continuing:

```sh
docker compose logs --tail 100 front jobs_scheduler simulators_repository
```

### 6. Validate the running framework

From `dist/deployment`, on the application server:

```sh
docker compose exec buildkit buildctl --addr tcp://127.0.0.1:64000 debug workers
curl --fail --retry 15 --retry-connrefused --retry-delay 2 http://127.0.0.1:63700/openapi.json
curl --fail http://127.0.0.1:63200/health
curl --fail http://127.0.0.1:63200/jobs
curl --head https://rtmf.example/auth/login
```

Expect a BuildKit worker, parser OpenAPI JSON, scheduler health HTTP 200, a JSON
job list, and a redirect to Keycloak. The `/jobs` request exercises the Slurm
adapter. Also run the
[authenticated in-container Slurm check](docs/INFRASTRUCTURE.md#verify-authentication-inside-the-application-container)
to verify JWT generation, username, and REST response errors directly. Health
status alone does not validate the external integrations.

Open your public frontend HTTPS URL and sign in with the Keycloak user created
in step 2. There is no built-in RTMF administrator password. Verify the
complete workflow using an operator-provided compatible sample simulator:

1. Register it and wait for a successful image build/push and digest lookup.
2. Submit a small simulation and confirm its Slurm job completes.
3. Open its results, confirming worker PostgreSQL writes and S3 result storage/readback.

The installation is ready for simulation use when this complete check succeeds.

## Normal operations

From the prepared `dist/deployment` directory:

```sh
docker compose ps -a
docker compose logs -f front
docker compose stop front
docker compose up -d --pull missing front
docker compose down
```

To change settings or image tags, edit the source manifest and render again,
then apply the [update procedure](docs/DEPLOYMENT.md#updates). Back up PostgreSQL
and S3 data separately. Frontend sessions reset on restart; parser and System
Discovery working files need explicit mounts to survive container recreation.

For a smaller installation, a parser-only first run, distributed deployment,
or troubleshooting, use [Deployment](docs/DEPLOYMENT.md).
