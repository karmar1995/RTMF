# Application images and release bundles

This page is for people building or publishing releases. For installation with
existing images, follow [Deployment](DEPLOYMENT.md).

## Build locally with Docker

Run from a full source checkout in Bash, with Docker Engine running. Set the
list to the application services you need, then build:

```bash
deployment_services=(front analytics jobs_scheduler matrix_generation simulators_repository visualization evaluator parser system_discovery)
for service in "${deployment_services[@]}"; do
  image_name="${service//_/-}"
  docker build -f "docker/$service/Dockerfile" -t "rtmf/$image_name:local" .
done
```

For example, to build only front and the simulator repository, replace the
first line with `deployment_services=(front simulators_repository)`. For a
single service:

```sh
docker build -f docker/parser/Dockerfile -t rtmf/parser:local .
```

Set `deployment.images.repository` to `rtmf` and `.tag` to `local` in the
manifest. Continue with [Deployment](DEPLOYMENT.md#full-framework-or-selected-services).
Its `up -d --pull missing` sequence uses the built images and downloads the
upstream BuildKit sidecar when needed. The loop does not build worker base
images used on compute nodes.

The scheduler Dockerfile accepts `RTMF_UID`, `RTMF_GID`, `SLURM_UID`, and
`SLURM_GID`. Set these with `docker build --build-arg NAME=value` if the site
requires different identities; see [Slurm preparation](INFRASTRUCTURE.md#slurm-and-compute-nodes).

## Publish built images

After building and testing, use the same Bash service list to tag and push the
images. Replace the placeholders with your registry host, namespace, and fixed
release tag:

```bash
docker login '<APP_REGISTRY_HOST>'
image_namespace='<APP_IMAGE_NAMESPACE>'
release_tag='<RELEASE_TAG>'
for service in "${deployment_services[@]}"; do
  image_name="${service//_/-}"
  image_ref="$image_namespace/$image_name:$release_tag"
  docker tag "rtmf/$image_name:local" "$image_ref"
  docker push "$image_ref"
done
```

Namespace `registry.example/rtmf` and tag `v1` produce images such as
`registry.example/rtmf/jobs-scheduler:v1`. Compose service names use
underscores; image names use hyphens. There is no persistent `job_executor`
image in this Dockerfile set.

A full simulation release also needs compatible worker base images and a
sample simulator; see [simulator infrastructure](INFRASTRUCTURE.md#simulator-images-and-registry).
Test login, simulator registration/image building, Slurm submission, and result
retrieval before publishing an installation as verified.

## Optional BuildKit build helper

Maintainers already using rootless BuildKit can use
`docker/scripts/docker_build_images.sh` instead of the Docker build loop. It
requires `buildctl` and a running `buildkitd`, separate from the runtime sidecar.
See [BuildKit rootless setup](https://github.com/moby/buildkit/blob/master/docs/rootless.md).

```sh
rootlesskit buildkitd
```

From another terminal, build and push all nine services:

```sh
docker/scripts/docker_build_images.sh \
  --registry '<APP_REGISTRY_HOST>' --project '<PROJECT>' --tag '<RELEASE_TAG>'
```

Add service names to select a subset. Authenticate using Docker-compatible
credentials via `DOCKER_CONFIG` / `--docker-config`, or the helper's
`HARBOR_USERNAME` and `HARBOR_PASSWORD` variables. Use `--buildkit-addr` for a
non-default socket. For Docker-loadable archives instead of pushing:

```sh
docker/scripts/docker_build_images.sh --local-build --load --tag local parser
```

Archives are written under `dist/images`. Omit `--load` to transfer them to
another host. Use `--help` for options or `--dry-run` to inspect commands.

## Package a deployment

A **kit** lets an operator edit templates and render their own installation:

```sh
./scripts/init_deployment.sh --target-dir /tmp/rtmf-kit
```

It includes public scripts/templates, installation docs, and the database
schema. It excludes source, Dockerfiles, and existing private configuration and
initializes its own blank `.env`. Supply the published image namespace/tag and
direct the operator to `docs/DEPLOYMENT.md` in the kit.

A **prepared bundle** is already rendered for a particular machine. Package it
without credentials:

```sh
tar --exclude='./.env' -C dist/deployment -czf /tmp/rtmf-deployment.tar.gz .
```

Check additional assets before distributing them; custom Compose fragments may
reference files the renderer does not copy. Supply those non-secret files and
ensure host paths/endpoints match the recipient's machine. The recipient follows
[Start a prepared bundle](DEPLOYMENT.md#start-a-prepared-bundle).
