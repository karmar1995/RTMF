# Prepare a single-server virtual machine

Deploy the complete RTMF application in a dedicated Linux virtual machine.
The VM runs all nine application services and their rootless BuildKit sidecar.
Slurm's controller, REST service, and compute nodes are deployed separately.
Keycloak, PostgreSQL, object storage, and Harbor can either be existing services
or run alongside RTMF inside this VM.

This runbook prepares the VM and its dependencies. Use the linked installation
sections for service-specific commands, then follow
[application deployment](DEPLOYMENT.md#full-framework-or-selected-services).
Examples assume Ubuntu 24.04 LTS on x86-64, systemd, and Bash; the scheduler's
library mounts and default worker platform use that architecture. Replace
`.example` names, `<...>` placeholders, addresses, and network ranges with
values agreed with your infrastructure administrators. External dependency
versions must be selected together; the repository has no tested version matrix
for the complete stack.

## 1. Create the isolation boundary

Create a VM used only for this deployment, on a dedicated private subnet or
VLAN. Give it a stable private address and DNS name. Expose the frontend through
an approved HTTPS ingress or a narrowly permitted HTTPS listener on the VM;
avoid assigning unrestricted public access to the guest. Provide SSH access
only through the management network or a bastion.

Use a supported, patched guest OS, SSH keys, a separate administrator account,
and synchronized time. Do not mount the hypervisor's filesystem or unrelated
infrastructure shares into the guest. Do not configure the VM as a router
between infrastructure networks. Keep the normal Docker networking required
inside the guest.

Allocate CPU/RAM for the application, concurrent image builds, and whichever
infrastructure services you host locally. As a sizing reference, Harbor alone
recommends 4 CPUs, 8 GB RAM, and 160 GB disk; that is **not** a size estimate for
the whole framework. Measure the pilot deployment and allow additional space
for image layers, simulation results, database growth, and backups. See
[Harbor prerequisites](https://goharbor.io/docs/main/install-config/installation-prereqs/).

Provision persistent disks before installing services. Account for these paths:

| Data | Default/example location |
| --- | --- |
| Checkout or deployment kit, private manifest, BuildKit configuration | `/srv/rtmf` |
| Docker images, containers, and BuildKit's named state volume | `/var/lib/docker` unless Docker's data root is explicitly moved |
| Locally installed PostgreSQL databases | The distribution's PostgreSQL data directory |
| Locally hosted S3 objects | `/srv/rtmf-minio` |
| Harbor registry data | Set `data_volume` to a persistent path such as `/srv/rtmf-harbor` |
| Keycloak installation files | `/srv/rtmf-keycloak`; its database must also be persistent |
| Shared Slurm working directory and logs | For example `/shared/rtmf`, provided by the cluster storage service |

Putting only `/srv/rtmf` on a large data disk does not move Docker's images or
database files there. Set ownership for each service and configure disk/log
retention. Back up PostgreSQL, object storage, registry data, identity data, and
private configuration using their respective backup procedures; a VM snapshot
alone is not a coordinated backup of external services.

## 2. Choose where dependencies run

The following inventory comes from the deployment manifest, Dockerfiles, and
the adapters used by the running application:

| Dependency | Placement and installation responsibility | Code/configuration evidence |
| --- | --- | --- |
| Docker Engine and Compose plugin | Install on the VM. They run the application and optional Keycloak/Harbor containers. | `scripts/deployment.py`, `docker/*/Dockerfile` |
| Python 3.11+, Bash, Git, `curl`, CA certificates | VM preparation tools. Python uses only its standard library for deployment. A kit needs no Git checkout. | `scripts/deployment.py`, `scripts/lib/deployment.py`, deployment shell wrappers |
| PostgreSQL server and `psql` | Existing database service or local server; install `psql` on the administration host for schema setup/checks. | `resources.jobs_database`, `resources.simulators_database`, `db_mgmt/` |
| S3-compatible storage and MinIO Client `mc` | Existing S3/MinIO/AIStor service or local installation; `mc` is an administration/checking tool. | `resources.aistor` and the three storage resources |
| Keycloak and its database | Existing identity service or a separate local Compose project. Frontend login requires it. | `runtime.services.use_case.authentication.keycloak` |
| OCI registry, such as Harbor | Existing compatible registry or install Harbor on the VM. Supplies worker bases and stores simulator builds. | `runtime.services.simulators_repository.build_worker`, `harbor_client.py` |
| Rootless BuildKit daemon | **Already supplied by Compose** as the pinned `moby/buildkit:v0.31.2-rootless` sidecar. Prepare its host configuration and kernel prerequisites below. | `deployment.services.simulators_repository.compose.services.buildkit` |
| `buildctl` | **Already included in the simulator-repository image**, copied from the matching BuildKit image. No host client installation is required for normal deployment. | `docker/simulators_repository/Dockerfile` |
| Slurm client binaries/plugins/libraries and Munge | Install compatible clients and a Munge daemon on the VM; controller, REST daemon, and compute daemons stay on the external cluster. | Scheduler Compose bind mounts, `src/adapters/slurm_adapter/slurm_token_refresher.py` |
| Apptainer, compatible worker bases, simulator execution dependencies | Prepare on compute nodes/in worker images, not as VM application packages. | `src/adapters/slurm_adapter/slurm_request_info.py`, `src/services/job_executor/` |
| DNS, NTP, TLS certificates, HTTPS reverse proxy | Use existing infrastructure or install a host reverse proxy such as Nginx. Time synchronization is needed for both authentication systems. | Frontend callback, Keycloak issuer, Slurm token authentication |

Python 3.12 and each application's Python packages are installed **inside its
image** by `docker/<service>/Dockerfile` and `requirements.txt`. Do not install
those packages into the VM's system Python. A host Go compiler is needed only
if building MinIO/`mc` from source there; it can instead live on a controlled
build host. No additional RTMF queue broker is required. Harbor manages its own
internal components through its installer.

## 3. Apply a network allowlist

Before starting services, configure a stateful firewall/security group at the
hypervisor or network boundary with default-deny ingress **and egress**. Permit
established response traffic and only the required source/destination pairs.
Apply the same policy to IPv6 if enabled. The examples below are default ports;
use the actual ports of your installation rather than opening whole networks.

### Connections into the VM

| Source | VM destination | When needed |
| --- | --- | --- |
| Management subnet/bastion | TCP 22 | Administration only. |
| Approved users or upstream reverse proxy | TCP 443 | Frontend HTTPS; also Keycloak HTTPS if hosted here. |
| Designated compute nodes | TCP 5432 | Only if the application PostgreSQL server is hosted here. |
| Designated compute nodes | TCP 9000, or the chosen S3 API port | Only if object storage is hosted here. |
| Compute nodes and approved image builders/administrators | TCP 5000, or the chosen simulator-registry port | Only if Harbor/the simulator registry is hosted here. |

Application containers also need access to locally hosted data and registry
services. Permit their actual Docker source/NAT addresses at the guest firewall
and database access rules. Keep PostgreSQL, S3, and registry access limited to
these application and compute clients; they are not public frontend endpoints.

Do not expose application ports `63000`–`63800` to other machines in this
single-server profile. Keep backend host publications on `127.0.0.1`, and set
`deployment.services.front.publish.host` to `127.0.0.1` for a host Nginx proxy
to port `63000`. Keep Keycloak's HTTP backend on `127.0.0.1:8080` and MinIO's
administration console on loopback. BuildKit port `64000` is container-network
only and must have no host publication. Do not expose the Docker daemon API or
Harbor's internal database/cache ports.

### Connections out of the VM and its containers

| Destination | Allowed traffic | Purpose |
| --- | --- | --- |
| Approved DNS resolver and time server | TCP/UDP 53; UDP 123, as used by the site | DNS and clock synchronization. |
| External Slurm REST host | TCP 6820, or its configured port | Scheduler API calls. |
| External Slurm controller | Controller RPC port, commonly TCP 6817 | Slurm client operations, including `scontrol token`. Add accounting traffic only if required by the site's client configuration. |
| External Keycloak issuer | TCP 443 | Discovery, login/token handling, signing keys. |
| External application PostgreSQL server | TCP 5432, or its configured port | Application database and, if applicable, the separate Keycloak database. |
| External S3 API | Chosen API port, commonly TCP 443 or 9000 | Object reads/writes. |
| Simulator registry | Its configured port, currently HTTP in this integration | Base pulls, simulator pushes, manifest lookup. |
| Application/container image registries | Their HTTPS endpoints | Pull application, BuildKit, Keycloak, and Harbor images as applicable. |
| Designated shared-storage server | For example TCP 2049 for an NFSv4-only export | Read job logs at the cluster's shared path, if used. |
| Approved OS/package mirrors or controlled egress proxy | Only required endpoints/ports | Updates, infrastructure installation, and image builds. |

Compute nodes independently need access to the application PostgreSQL database,
S3 API, and simulator registry, whether those services are external or hosted
on this VM. Opening only VM-to-cluster connections is insufficient. Ask the
cluster administrator to allow these compute-to-service connections explicitly.

Builds may fetch Docker base images, Debian packages, and Python packages. The
simulator Dockerfile generator also uses `download.pytorch.org/whl/cpu` when
installing PyTorch. Provide approved mirrors/proxy access or prebuilt inputs;
an unrestricted Internet route is not a prerequisite. Users' browsers currently
load Bootstrap CSS/JavaScript from `cdn.jsdelivr.net` in the frontend template.
Allow that browser access or vendor those assets before an offline deployment.

**Docker firewall handling matters:** Docker-published traffic can bypass UFW's
normal host filtering. Enforce the allowlist outside the VM, including traffic
forwarded/NATed for containers. If guest rules are also used, configure them for
the selected Docker iptables/nftables backend and its forwarding path. Do not
disable Docker's firewall rules or forwarding to obtain isolation; that can
break container networking. Use a current patched Docker release; releases
before 28.0.0 also have a documented same-L2 exception to loopback publication.
See [Docker firewall behavior](https://docs.docker.com/engine/network/packet-filtering-firewalls/)
and [port publication](https://docs.docker.com/engine/network/port-publishing/).

## 4. Install the VM tools and obtain deployment files

On the VM, after allowing the approved package sources:

```sh
sudo apt update
sudo apt install -y bash ca-certificates curl git openssl python3 postgresql-client
```

Register Docker's official apt repository using the
[Ubuntu installation instructions](https://docs.docker.com/engine/install/ubuntu/),
then install Engine and the plugins from that repository:

```sh
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
python3 --version
timedatectl status
```

Python must be at least 3.11. Restrict Docker access to trusted operators: its
socket and the `docker` group grant control equivalent to root in the VM. The
remaining deployment commands assume the operator has that access; otherwise
use the site's approved `sudo` procedure. Configure Docker log rotation and
disk monitoring as described in [Docker post-installation](https://docs.docker.com/engine/install/linux-postinstall/).

Create a private working directory owned by the deployment operator:

```sh
sudo install -d -m 0700 -o "$(id -un)" -g "$(id -gn)" /srv/rtmf
```

Place the release's source checkout or exported deployment kit there. A kit
contains deployment tools and documentation but requires published application
images. For a source installation, use the repository/release supplied by the
maintainer, then initialize from its root:

```sh
cd /srv/rtmf
git clone '<REPOSITORY_URL>' server
cd server
git checkout '<RELEASE_REF>'
./scripts/init_deployment.sh
```

For a kit, run only the initialization command from the kit root. Keep the
generated `config/deployment.json` and `dist/deployment/.env` private. The
following sections describe how to fill their infrastructure settings before
rendering or starting the application.

## 5. Connect the VM to the external Slurm cluster

Have the cluster administrator provide the submit account/UID/GID, permitted
partition, client packages and plugins, `slurm.conf`, Munge authentication
integration, REST URL/API version, and shared working-directory convention.
The VM is a Slurm **client host**; do not install a controller or compute daemon
there. Limit its cluster access to the controller/REST/storage paths above.

Install the cluster-compatible Slurm client packages and Munge from the site's
package source. For an Ubuntu-packaged cluster this typically means
`slurm-client` and `munge`, with their matching libraries/plugins, but do not
blindly use the guest distribution's Slurm version against a different cluster
release. The executable and plugins must also work with the scheduler image's
libraries. Follow [scheduler host preparation](INFRASTRUCTURE.md#prepare-the-scheduler-applications-host)
for the bind mounts and container identity.

The cluster administrator must securely supply the Munge key/configuration for
this authentication domain. Keep the key owned by `munge`, mode `0600`; start
the local Munge service after installing the correct key and verify the socket
is available. The scheduler needs the socket, **not** the controller's private
JWT signing key. The default Compose mounts require these host assets:

```text
/usr/bin/scontrol
/etc/slurm
/usr/lib/x86_64-linux-gnu/slurm
/lib/x86_64-linux-gnu/libmunge.so.2
/run/munge
```

Check `ldd /usr/bin/scontrol`, then check its dependencies again inside the
running scheduler container. Adapt the manifest's individual read-only mounts
to the installed client; do not mount the whole host filesystem to satisfy
missing libraries.

Match the scheduler process's numeric UID/GID to the intended submit identity
and give it access to the Munge socket. If necessary, rebuild its image with
the documented `RTMF_UID`, `RTMF_GID`, `SLURM_UID`, and `SLURM_GID` build arguments.
`SLURM_USER_NAME` must match the user represented by `scontrol token`; setting
that string does not change the process UID or impersonate another account.
The cluster must permit token creation and expose a REST API version compatible
with the adapter. The template's `v0.0.43` is only an example. See
[Slurm authentication](INFRASTRUCTURE.md#enable-restjwt-authentication).

If using shared job logs, arrange an export with the cluster administrator.
For NFSv4, install `nfs-common`, mount only the designated export at
`/shared/rtmf`, and persist that mount through the site's systemd/fstab
procedure. The VM's log-reading mount can be read-only; compute nodes need the
same path writable by the submit user. Ensure the mount is available before
starting the scheduler. Replace the template's `/tmp/workspace` bind mount and
set these fields under `runtime.services.jobs_scheduler.slurm`:

```json
{
  "working_directory": "/shared/rtmf",
  "stdout": "/shared/rtmf/%A_%a.out",
  "stderr": "/shared/rtmf/%A_%a.err"
}
```

The directory must already exist; flat filenames avoid Slurm opening logs in
per-job directories that have not yet been created. Before application startup,
run as the submit user on the VM:

```sh
scontrol ping
sinfo
scontrol token lifespan=900 >/dev/null
sbatch --wait --chdir=/shared/rtmf --output=/shared/rtmf/vm-check-%j.out --wrap='hostname'
```

Apply the site's partition/account options. Confirm the resulting log can be
read on the VM. The cluster administrator must install Apptainer on compute
nodes and validate worker-image pulls, database access, and S3 access there;
see [compute preparation](INFRASTRUCTURE.md#install-apptainer-and-prepare-compute-paths).

## 6. Provision PostgreSQL and S3 storage, locally or externally

### Existing PostgreSQL + MinIO/S3 bundle

Obtain the database host/port, an application role/database, S3 API endpoint,
bucket-scoped credentials, TLS requirements, and any private CA certificates.
Allow the VM/application containers and compute nodes to reach both services.
Run the [database initialization and sanity check](INFRASTRUCTURE.md#remote-or-managed-postgresql)
and [bucket/user setup](INFRASTRUCTURE.md#create-buckets-and-an-application-identity)
against those external systems. Hosting them together does not change either
protocol or remove the need for separate credentials.

### Host the bundle in the framework VM

Install PostgreSQL using the [local database instructions](INFRASTRUCTURE.md#postgresql-one-application-database):

```sh
sudo apt install -y postgresql postgresql-client
sudo systemctl enable --now postgresql
```

Create the role/database and run the ordered `db_mgmt` scripts from that guide.
Use **one initialized RTMF application database** for both application DSNs;
the schema contains cross-service references. Keycloak, if hosted here, needs
its own separate database and role. Do not use Harbor's bundled database as
the RTMF database.

Configure PostgreSQL `listen_addresses`, `pg_hba.conf`, and guest firewall rules
for the VM's private interface, required Docker clients, and designated compute
clients only. Use password authentication and the site's TLS policy; avoid
`trust` rules or unrestricted client ranges. For exact setup see
[database connection rules](INFRASTRUCTURE.md#allow-application-and-compute-connections).

Install a selected S3 implementation using
[object-storage installation](INFRASTRUCTURE.md#install-or-obtain-an-s3-api),
including `mc` for administration and checks. The MinIO Community repository
was archived on April 25, 2026, and its source-only distribution should not be
treated as a maintained `minio/minio:latest` release. Choose an approved storage
release/provider and maintenance plan; the linked source-build example needs
a Go toolchain compatible with the selected revisions. You can build verified
binaries on a separate build host and install them on the VM instead. See the
[MinIO upstream repository](https://github.com/minio/minio).

For the standalone MinIO systemd example, store data under `/srv/rtmf-minio`
and bind the S3 API to the VM's private address. Bind the administration console
to loopback. For example, replace the unit's `ExecStart` with the following,
substituting the VM's actual private IP for `10.20.0.10`:

```ini
ExecStart=/usr/local/bin/minio server /srv/rtmf-minio --address 10.20.0.10:9000 --console-address 127.0.0.1:9001
```

Reload systemd and restart the service after editing the unit. Keep the storage
administrator credentials separate from the application's bucket identity.
Create `jobs-results`, `tmp`, and `system-discovery` and grant the application
identity access to those buckets using the linked instructions.

### Configure either placement

Set `RTMF_JOBS_POSTGRES_DSN` and
`RTMF_SIMULATORS_REPOSITORY_POSTGRES_DSN` in `.env` to the same application
database. Set `resources.aistor.endpoint` to the S3 **API** host/port without a
scheme, `.secure` to its TLS setting, and `RTMF_AISTOR_ACCESS_KEY` /
`RTMF_AISTOR_SECRET_KEY` to the application identity. The submitted worker must
use matching TLS/bucket settings too.

Use private DNS names reachable from both containers and compute nodes, even
for VM-hosted services. Container `localhost` refers to the container, and a
worker's `localhost` refers to the compute environment. Install/mount required
CA files into every container/worker that uses them. Verify schema access and
object upload/read/list/delete with the application credentials from both the
VM and a compute node before continuing.

## 7. Connect to Keycloak or host it here

For an **external Keycloak**, obtain the stable HTTPS issuer URL and arrange
the realm/client/permissions/user configuration in [Keycloak setup](KEYCLOAK.md).
Permit VM/container egress to the issuer, and ensure users' browsers can reach
the same URL. Do not substitute an internal HTTP address for the browser's
issuer in application configuration.

For a **locally hosted Keycloak**, follow [Keycloak server installation](INFRASTRUCTURE.md#keycloak-server)
to create its dedicated PostgreSQL database/role and `/srv/rtmf-keycloak`
Compose project. Select a fixed Keycloak image version, use production `start`,
persist its database, and publish the HTTP backend only on `127.0.0.1:8080`.
Configure the public hostname and trusted proxy headers as shown there. Put
Nginx HTTPS in front of that backend; remove temporary bootstrap administrator
access after creating the permanent administrator. See
[Keycloak container deployment](https://www.keycloak.org/server/containers).

For either placement, configure the `rtmf` realm, `rtmf-web` login client,
`rtmf-use-case` audience/permissions, and first user's roles. The HTTPS callback
must be the frontend's exact `/auth/callback` URL. Set the manifest's
`runtime.services.use_case.authentication.keycloak` fields and frontend callback,
and fill the Keycloak/application secrets in `.env` as described in
[deployment credentials](DEPLOYMENT.md#3-fill-credentials).

Install Nginx on this VM if it is the HTTPS edge:

```sh
sudo apt install -y nginx
```

Provision DNS and certificates through the site's CA/ACME process, then install
the [HTTPS proxy configuration](INFRASTRUCTURE.md#public-https-access) for
`rtmf.example` and, if hosted here, `identity.example`. Use the site's approved
certificate renewal path; open TCP 80 only if that path requires it. Validate:

```sh
sudo nginx -t
curl --fail https://identity.example/realms/rtmf/.well-known/openid-configuration
```

The returned issuer must match the configured HTTPS issuer exactly. Repeat the
discovery check from the application container after startup and from a user's
browser network; locally hosted identity must also be reachable by containers
through its public hostname/private routing.

## 8. Provide Harbor or a compatible simulator-image registry

For an existing registry, obtain the endpoint, projects, accounts, and compatible
worker base images. For local Harbor, follow the fixed-version installer in
[Harbor installation](INFRASTRUCTURE.md#install-harbor-or-use-an-existing-oci-registry).
Docker/Compose are already installed. Configure a persistent `data_volume`,
private registry DNS, and an internal listener such as port `5000`; avoid
colliding with the frontend/identity proxy on port `443`.

The current simulator integration explicitly builds/pushes using HTTP and
launches `apptainer --no-https`. Use its HTTP endpoint only on the controlled
internal network. An HTTPS-only simulator registry needs integration changes;
application image registries can use HTTPS independently.

Create `base` and `rtmf-simulators` projects. Give the repository account pull
access to bases and push/pull access to simulator images; give compute workers
a separate simulator pull account. Set:

- `runtime.services.simulators_repository.build_worker.harbor_registry` to the
  bare host/port, e.g. `registry.internal.example:5000`, and `.harbor_project`
  to `rtmf-simulators`.
- `RTMF_HARBOR_USERNAME` / `RTMF_HARBOR_PASSWORD` to the repository account.
- `APPTAINER_DOCKER_USERNAME` / `APPTAINER_DOCKER_PASSWORD` to the compute account.

The current digest lookup uses a Basic-authenticated manifest `HEAD` request
and does not perform a registry Bearer-token exchange. Run the
[manifest-access check](INFRASTRUCTURE.md#worker-base-images-are-an-additional-prerequisite)
with the real repository credentials. A Harbor endpoint returning a Bearer
challenge needs a compatible integration/endpoint before registration works;
successful `docker login` or push alone is insufficient. Retain registry access
controls when resolving this requirement.

Obtain tested worker base images with the expected executor entry point,
`/opt/simulator/.venv`, and runtime configuration. The application image build
does not create them. The older worker helper scripts require packaging fixes
before use with this checkout; the linked worker-base section records the
current requirements. Validate a real base pull on a compute node. If Docker
is used to push bases to an HTTP registry, configure that builder's daemon for
the specific insecure registry as described in the infrastructure guide.

## 9. Prepare rootless BuildKit and its bundled client

Do not install a second host `buildkitd` for the normal Compose deployment.
Selecting `simulators_repository` starts the sidecar on its separate Docker
network, and the application image already has `buildctl`. Keep
`build_worker.buildkit_addr` as `tcp://buildkit:64000`. Preserve the template's
state volume, health check, and rootless container security options. No Docker
socket mount or privileged application container is required.

The VM kernel must support unprivileged user namespaces. Check that
`user.max_user_namespaces` is nonzero. If the daemon cannot start because the
guest distribution's AppArmor policy blocks user namespaces, follow the
[BuildKit rootless guidance](https://github.com/moby/buildkit/blob/master/docs/rootless.md)
for that distribution. Apply any required policy exception inside this
dedicated VM and retain the outer VM/network boundary; do not change the
hypervisor's policy or replace the sidecar with a privileged container.

For HTTP worker-base pulls, create `/srv/rtmf/buildkitd.toml` readable by the
sidecar user, substituting the real registry address:

```toml
[registry."registry.internal.example:5000"]
  http = true
```

In `config/deployment.json`, edit
`deployment.services.simulators_repository.compose.services.buildkit.command`:

```json
["--addr", "tcp://0.0.0.0:64000", "--config", "/etc/buildkit/buildkitd.toml"]
```

Append this bind to that sidecar's existing `volumes` list, keeping the named
state volume:

```json
{
  "type": "bind",
  "source": "/srv/rtmf/buildkitd.toml",
  "target": "/etc/buildkit/buildkitd.toml",
  "read_only": true,
  "bind": {"create_host_path": false}
}
```

The file is a host asset, not something the renderer copies into a bundle.
This listener binds inside the container network; it must remain unpublished
on the VM. Keep BuildKit and its copied client versions aligned if overriding
the pinned image/build argument.

## 10. Start the application and verify the boundaries

Return to [full-framework deployment](DEPLOYMENT.md#full-framework-or-selected-services)
to obtain/build application images, finish the manifest and secrets, render,
validate, and start all nine services. Keep `deployment.local_endpoints=true`
so internal application calls use Docker DNS. Do not change container REST
listeners to loopback; the **host publications** provide the loopback boundary.

After startup, from the generated Compose directory:

```sh
docker compose ps -a
docker compose exec buildkit buildctl --addr tcp://127.0.0.1:64000 debug workers
docker compose exec simulators_repository buildctl --version
docker compose exec jobs_scheduler ldd /usr/bin/scontrol
```

Run the [in-container Slurm authentication check](INFRASTRUCTURE.md#verify-authentication-inside-the-application-container).
Verify database/S3/identity/registry access from the actual containers and
compute nodes, then sign in, register a compatible sample simulator, submit a
small job, and retrieve its logs/results. Service health checks alone do not
verify that complete path.

Inspect Compose publications and guest listeners (`docker compose ps` and
`sudo ss -lntup`). From another machine outside the allowlist, verify that
backend ports, BuildKit, identity HTTP, and administration consoles cannot be
reached. Verify denied destinations from both the VM and an application
container as well as successful allowlisted connections; guest-only checks do
not prove Docker egress is filtered. Record the dependency versions, firewall
rules, identities, storage locations, and successful checks for the test
deployment and subsequent upgrades.
