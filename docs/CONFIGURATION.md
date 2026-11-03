# Configuration reference

For installation steps, use [Deploy RTMF](DEPLOYMENT.md). Deployment
preparation uses Python 3.11+ and the standard library; application packages are
not required on the host.

## Inputs and outputs

| File | Role |
| --- | --- |
| `config/deployment.example.json` | Public template. |
| `config/deployment.json` | Editable, machine-specific manifest; ignored by Git. |
| `dist/deployment/.env` | Editable credentials; ignored by Git and preserved by rendering. |
| `dist/deployment/compose.yaml` | Generated Compose application for this machine. |
| `dist/deployment/services/<name>/rtmf.main.json` | Expanded runtime configuration for one service. |
| `dist/deployment/environment.json`, `.env.example` | Generated required/optional variable names and blank template. |

Applications read ordinary JSON selected by `RTMF_MAIN_CONFIGURATION_FILE`.
They load only their own `services.<name>` section before environment
interpolation. Front also composes `services.use_case` in the same process.
Applications do not read the deployment manifest or resolve its references.

## Manifest fields

| Section | Purpose |
| --- | --- |
| `version` | Schema version, currently `1`. |
| `defaults` | Reusable settings, such as application binding and cookies. |
| `resources` | Named database/storage connections and execution identity. |
| `endpoints` | Outbound client configuration for local or remote servers. |
| `runtime.services` | Configuration passed to each service's composition package. |
| `deployment.name` | Compose project name; default `rtmf`. |
| `deployment.local_endpoints` | Map selected local endpoints to Docker URLs; default `true`. |
| `deployment.images` | Image `repository` prefix and `tag`. |
| `deployment.services` | Services installed here, port publication, and infrastructure fragments. |

Render all entries under `deployment.services`, or pass service names to render
a subset. A front-only host needs front and its in-process use-case configuration;
its remote servers do not need deployment entries or runtime configuration.

```sh
./scripts/render_deployment.py --help
./scripts/render_deployment.py --check
./scripts/render_deployment.py --check --check-env
./scripts/render_deployment.py front --output-dir /srv/rtmf-front
```

`--check` validates without writing; `--check-env` additionally requires all
selected services' required variables to be nonblank. Validation covers local
references, selected services, image/project names, ports, and collisions.
Application-specific checks remain in each composition package.

## References

A local JSON pointer copies a shared value, then merges sibling overrides:

```json
{
  "$ref": "#/resources/aistor",
  "bucket": "jobs-results"
}
```

Objects merge recursively; lists/scalars replace defaults. References can also
copy a scalar or list. JSON pointer escaping (`~0`, `~1`) is supported. External
references, missing targets, and cycles are rejected. Generated JSON contains
expanded values and environment placeholders, with no `$ref` objects.

## Listening addresses and client URLs

- `runtime.services.<name>.rest`: where the application listens inside its container.
- `deployment.services.<name>.publish`: host bind address and port. Omit it or use `null` for no publication.
- `endpoints.<name>.base_url`: where clients reach that service.

The template listens on `0.0.0.0:8000` inside containers. Host ports are listed in
[Deployment](DEPLOYMENT.md#services-and-ports). The renderer derives
Compose's target port from runtime JSON.

Backend host ports bind to `127.0.0.1` by default. Selected services on the same
machine communicate over Docker DNS. To serve clients on another machine,
change `deployment.services.<name>.publish.host` to an internal interface and
set the clients' endpoint URLs accordingly. The operator must restrict the
published address and port to the internal network, including when changing
the port. Backend APIs rely on that network boundary for access control.

References to endpoints for selected local services use `http://<service>:<port>`.
Unselected endpoints retain their explicit remote URLs. The deployment entry's
`endpoint` chooses the logical endpoint name; by default it matches the service
name when present. `matrix_generation` maps to `matrix_generator` in the template.
Set `endpoint` to `null` per service, or `deployment.local_endpoints` to `false`,
to keep explicit URLs. A client reference with its own `base_url` override also
keeps that URL. Compute-node storage addresses must remain reachable from Slurm.

## Images and Compose extensions

Repository `registry.example/rtmf`, tag `v1`, and service `jobs_scheduler`
produce `registry.example/rtmf/jobs-scheduler:v1`. An entry can override
`image`, including a digest; CLI `--image` overrides one selected service.
The default repository/tag are `rtmf`/`latest`; they are naming defaults,
not an existing public release.

Each service's optional `compose` object accepts `services`, `volumes`, `networks`,
`configs`, and `secrets`. The template uses it for Slurm mounts and BuildKit.
Primary application image, environment, configuration mount, ports, and
`network_mode` are managed by the renderer. Extra mounts are appended; labels
must be a mapping. Application services join the shared default network.
BuildKit also uses a private network and persistent state.

Fragments accept manifest references, but not environment interpolation. Host
bind paths must exist. Additional relative paths resolve from the generated
bundle; the renderer does not copy those assets.

## Environment values

Required placeholders use `${NAME}`; defaults use `${NAME:default}`. Optional
empty tokens use `${NAME:}`. Only variables used by selected runtime sections
are passed to containers. The renderer never fills secret values into JSON.
Service startup rejects missing, empty, and whitespace-only required values.

Compose reads `.env` beside `compose.yaml`; shell values take precedence. Use
single-quoted literal values such as `NAME='value'`. The optional Python wrappers
and `--check-env` read a simpler literal format: blank/comment lines, `KEY=value`,
and matching outer quotes, with no expansion, escape decoding, or inline comments.
Use the simple single-quoted format for both paths. See Docker's
[interpolation reference](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)
for Compose-specific behavior.

For development without rendering, use `config/rtmf.local.example.json` and
the [source startup guide](STARTUP.md).
