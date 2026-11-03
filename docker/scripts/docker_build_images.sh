#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

DEFAULT_SERVICES=(
  front
  analytics
  jobs_scheduler
  matrix_generation
  simulators_repository
  visualization
  evaluator
  parser
  system_discovery
)

declare -A IMAGE_NAMES=(
  [front]="front"
  [analytics]="analytics"
  [jobs_scheduler]="jobs-scheduler"
  [matrix_generation]="matrix-generation"
  [simulators_repository]="simulators-repository"
  [visualization]="visualization"
  [evaluator]="evaluator"
  [parser]="parser"
  [system_discovery]="system-discovery"
)

declare -A SERVICE_PORTS=(
  [front]="5000"
  [analytics]="9500"
  [jobs_scheduler]="8600"
  [matrix_generation]="8700"
  [simulators_repository]="10000"
  [visualization]="8000"
  [evaluator]="8800"
  [parser]="8005"
  [system_discovery]="8010"
)

TEMP_DOCKER_CONFIG_DIR=""

usage() {
  cat <<'EOF'
Usage:
  docker/scripts/docker_build_images.sh [options] [service...]

Examples:
  docker/scripts/docker_build_images.sh --registry harbor.example.com --project rtmf analytics
  docker/scripts/docker_build_images.sh --registry harbor.example.com --project rtmf
  docker/scripts/docker_build_images.sh --local-build --tag dev analytics
  docker/scripts/docker_build_images.sh --local-build --load --tag dev analytics
  docker/scripts/docker_build_images.sh --dry-run --registry harbor.example.com --project rtmf analytics

Options:
  --tag TAG             Override image tag. Default: current Git short SHA.
  --registry REGISTRY   Harbor registry. May also be provided by HARBOR_REGISTRY.
  --project PROJECT     Harbor project. May also be provided by HARBOR_PROJECT.
  --push                Explicitly select Harbor/registry push mode. Default.
  --local-build         Build Docker-loadable local development image archive(s).
  --local-namespace NS  Local image namespace. May also be RTMF_LOCAL_IMAGE_NAMESPACE. Default: rtmf.
  --output-dir DIR      Directory for local image archives. Default: dist/images.
  --load                Valid only with --local-build; run docker load after building.
  --no-load             Valid only with --local-build; do not load after building.
  --platform PLATFORM   Optional single target platform. May also be DOCKER_PLATFORM.
  --buildkit-addr ADDR  Override BuildKit address. May also be BUILDKIT_ADDR.
  --docker-config DIR   Existing Docker-compatible auth config directory for push.
  --latest              In push mode, also push the same image as latest.
  --dry-run             Print commands without executing them.
  -h, --help            Show this help.

Default services:
  front analytics jobs_scheduler matrix_generation simulators_repository
  visualization evaluator parser system_discovery

Notes:
  This script uses BuildKit buildctl, not Docker Buildx. It expects a running
  rootless BuildKit daemon and does not start buildkitd automatically.
EOF
}

die() {
  echo "error: $*" >&2
  echo >&2
  usage >&2
  exit 1
}

cleanup() {
  if [[ -n "$TEMP_DOCKER_CONFIG_DIR" ]]; then
    rm -rf "$TEMP_DOCKER_CONFIG_DIR"
  fi
}
trap cleanup EXIT

shell_quote() {
  printf '%q' "$1"
}

print_command() {
  local first=true
  local part
  for part in "$@"; do
    if [[ "$first" == true ]]; then
      first=false
    else
      printf ' '
    fi
    shell_quote "$part"
  done
  printf '\n'
}

resolve_tag() {
  if [[ -n "$TAG_ARG" ]]; then
    IMAGE_TAG="$TAG_ARG"
  elif [[ -n "${IMAGE_TAG:-}" ]]; then
    IMAGE_TAG="${IMAGE_TAG}"
  else
    if ! IMAGE_TAG="$(git rev-parse --short=12 HEAD 2>/dev/null)"; then
      die "IMAGE_TAG is not set, --tag was not provided, and current directory is not a Git repository"
    fi
  fi

  [[ -n "$IMAGE_TAG" ]] || die "image tag cannot be empty"
  if [[ ! "$IMAGE_TAG" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
    die "image tag must be a valid Docker tag: $IMAGE_TAG"
  fi
}

validate_service() {
  local service="$1"
  if [[ -z "${IMAGE_NAMES[$service]+x}" ]]; then
    die "unknown service: $service"
  fi

  local dockerfile
  dockerfile="$(dockerfile_for_service "$service")"
  if [[ ! -f "$dockerfile" ]]; then
    die "missing Dockerfile for service $service: $dockerfile"
  fi
}

image_name_for_service() {
  local service="$1"
  printf '%s' "${IMAGE_NAMES[$service]}"
}

dockerfile_for_service() {
  local service="$1"
  printf 'docker/%s/Dockerfile' "$service"
}

port_for_service() {
  local service="$1"
  printf '%s' "${SERVICE_PORTS[$service]}"
}

unix_socket_from_addr() {
  local addr="$1"
  if [[ "$addr" == unix://* ]]; then
    printf '%s' "${addr#unix://}"
  fi
}

validate_buildkit_addr() {
  local addr="$1"
  local socket_path
  socket_path="$(unix_socket_from_addr "$addr")"
  if [[ -n "$socket_path" && ! -S "$socket_path" ]]; then
    return 1
  fi
  return 0
}

resolve_buildkit_addr() {
  if [[ -n "$BUILDKIT_ADDR_ARG" ]]; then
    BUILDKIT_ADDR_RESOLVED="$BUILDKIT_ADDR_ARG"
  elif [[ -n "${BUILDKIT_ADDR:-}" ]]; then
    BUILDKIT_ADDR_RESOLVED="${BUILDKIT_ADDR}"
  elif [[ -S "/run/user/$(id -u)/buildkit/buildkitd.sock" ]]; then
    BUILDKIT_ADDR_RESOLVED="unix:///run/user/$(id -u)/buildkit/buildkitd.sock"
  elif [[ -S "/run/buildkit/buildkitd.sock" ]]; then
    BUILDKIT_ADDR_RESOLVED="unix:///run/buildkit/buildkitd.sock"
  elif [[ "$DRY_RUN" == true ]]; then
    BUILDKIT_ADDR_RESOLVED="unix:///run/user/$(id -u)/buildkit/buildkitd.sock"
    echo "warning: BuildKit daemon socket was not found; dry-run is using $BUILDKIT_ADDR_RESOLVED" >&2
    return 0
  else
    echo "error: BuildKit daemon not found. Start rootless BuildKit, e.g. rootlesskit buildkitd, or set BUILDKIT_ADDR=unix:///path/to/buildkitd.sock." >&2
    exit 1
  fi

  if ! validate_buildkit_addr "$BUILDKIT_ADDR_RESOLVED"; then
    echo "error: BuildKit unix socket not found for $BUILDKIT_ADDR_RESOLVED. Start rootless BuildKit, e.g. rootlesskit buildkitd, or set BUILDKIT_ADDR=unix:///path/to/buildkitd.sock." >&2
    exit 1
  fi
}

validate_harbor_registry() {
  local registry="$1"
  [[ -n "$registry" ]] || die "push mode requires a registry"
  if [[ "$registry" == http://* || "$registry" == https://* ]]; then
    die "push mode registry must not include http:// or https://: $registry"
  fi
}

harbor_image_ref_for_service() {
  local service="$1"
  local registry="$2"
  local project="$3"
  local tag="$4"
  local image_name

  [[ -n "$registry" ]] || die "push mode requires a registry"
  [[ -n "$project" ]] || die "push mode requires a project"
  image_name="$(image_name_for_service "$service")"
  printf '%s/%s/%s:%s' "${registry%/}" "${project#/}" "$image_name" "$tag"
}

local_image_ref_for_service() {
  local service="$1"
  local tag="$2"
  local image_name
  image_name="$(image_name_for_service "$service")"
  printf '%s/%s:%s' "${LOCAL_IMAGE_NAMESPACE%/}" "$image_name" "$tag"
}

archive_path_for_service() {
  local service="$1"
  local image_name
  image_name="$(image_name_for_service "$service")"
  printf '%s/%s-%s.docker.tar' "$OUTPUT_DIR" "$image_name" "$IMAGE_TAG"
}

base64_auth() {
  printf '%s:%s' "$1" "$2" | base64 | tr -d '\n'
}

prepare_docker_config() {
  ACTIVE_DOCKER_CONFIG=""

  if [[ -n "$DOCKER_CONFIG_ARG" ]]; then
    [[ -d "$DOCKER_CONFIG_ARG" ]] || die "--docker-config directory does not exist: $DOCKER_CONFIG_ARG"
    ACTIVE_DOCKER_CONFIG="$DOCKER_CONFIG_ARG"
    return 0
  fi

  if [[ -n "${DOCKER_CONFIG:-}" ]]; then
    [[ -d "$DOCKER_CONFIG" ]] || die "DOCKER_CONFIG directory does not exist: $DOCKER_CONFIG"
    ACTIVE_DOCKER_CONFIG="$DOCKER_CONFIG"
    return 0
  fi

  local username="${HARBOR_USERNAME:-${HARBOR_USER:-}}"
  local password="${HARBOR_PASSWORD:-${HARBOR_PASS:-}}"
  if [[ -z "$username" || -z "$password" ]]; then
    if [[ "$DRY_RUN" == true ]]; then
      ACTIVE_DOCKER_CONFIG="<registry-auth-required>"
      echo "warning: push mode requires registry auth for execution; dry-run is continuing without credentials" >&2
      return 0
    fi
    die "push mode requires registry auth through --docker-config, DOCKER_CONFIG, or HARBOR_USERNAME/HARBOR_PASSWORD (or HARBOR_USER/HARBOR_PASS)"
  fi

  TEMP_DOCKER_CONFIG_DIR="$(mktemp -d)"
  local config_path="$TEMP_DOCKER_CONFIG_DIR/config.json"
  local auth
  auth="$(base64_auth "$username" "$password")"

  cat > "$config_path" <<EOF
{
  "auths": {
    "${REGISTRY%/}": {
      "auth": "$auth",
      "username": "$username",
      "password": "$password"
    },
    "http://${REGISTRY%/}": {
      "auth": "$auth",
      "username": "$username",
      "password": "$password"
    },
    "https://${REGISTRY%/}": {
      "auth": "$auth",
      "username": "$username",
      "password": "$password"
    }
  }
}
EOF
  chmod 600 "$config_path"
  ACTIVE_DOCKER_CONFIG="$TEMP_DOCKER_CONFIG_DIR"
}

buildctl_base_cmd() {
  local service="$1"
  local dockerfile
  dockerfile="$(dockerfile_for_service "$service")"

  BUILDCTL_CMD=(
    buildctl
    --addr "$BUILDKIT_ADDR_RESOLVED"
    build
    --frontend dockerfile.v0
    --local "context=$ROOT_DIR"
    --local "dockerfile=$ROOT_DIR"
    --opt "filename=$dockerfile"
  )

  if [[ -n "$PLATFORM" ]]; then
    BUILDCTL_CMD+=(--opt "platform=$PLATFORM")
  fi
}

run_buildctl() {
  if [[ "$MODE" == push ]]; then
    if [[ "$DRY_RUN" == true ]]; then
      printf 'DOCKER_CONFIG='
      shell_quote "$ACTIVE_DOCKER_CONFIG"
      printf ' '
      print_command "${BUILDCTL_CMD[@]}"
    else
      DOCKER_CONFIG="$ACTIVE_DOCKER_CONFIG" "${BUILDCTL_CMD[@]}"
    fi
  else
    if [[ "$DRY_RUN" == true ]]; then
      print_command "${BUILDCTL_CMD[@]}"
    else
      "${BUILDCTL_CMD[@]}"
    fi
  fi
}

build_service_push() {
  local service="$1"
  local image_ref="$2"

  buildctl_base_cmd "$service"
  BUILDCTL_CMD+=(--output "type=image,name=$image_ref,push=true")

  echo "Service: $service"
  echo "Dockerfile: $(dockerfile_for_service "$service")"
  echo "Image: $image_ref"
  echo "Command:"
  run_buildctl
  echo
}

build_service_local() {
  local service="$1"
  local image_ref="$2"
  local archive_path
  archive_path="$(archive_path_for_service "$service")"

  buildctl_base_cmd "$service"
  BUILDCTL_CMD+=(--output "type=docker,name=$image_ref,dest=$archive_path")

  echo "Service: $service"
  echo "Dockerfile: $(dockerfile_for_service "$service")"
  echo "Image: $image_ref"
  echo "Archive: $archive_path"
  echo "Command:"
  run_buildctl

  if [[ "$LOAD" == true ]]; then
    echo "Load command:"
    print_command docker load -i "$archive_path"
    if [[ "$DRY_RUN" == false ]]; then
      docker load -i "$archive_path"
      echo "Loaded image $image_ref into local Docker."
    fi
  fi

  print_local_run_instructions "$service" "$image_ref" "$archive_path"
}

print_local_run_instructions() {
  local service="$1"
  local image_ref="$2"
  local archive_path="$3"
  local port
  port="$(port_for_service "$service")"

  cat <<EOF

Built local Docker image archive:
  $archive_path

Load it with:
  docker load -i $archive_path

Run it with:
  docker run --rm $image_ref

Port-mapped run:
  docker run --rm -p $port:$port $image_ref

Config-aware run template:
  docker run --rm \\
    -e RTMF_MAIN_CONFIGURATION_FILE=/etc/rtmf/rtmf.main.json \\
    -v "\$PWD/config/rtmf.main.json:/etc/rtmf/rtmf.main.json:ro" \\
    -p $port:$port \\
    $image_ref

Real service execution also requires RTMF_MAIN_CONFIGURATION_FILE, config volume mounts, and service-specific environment variables.

EOF
}

TAG_ARG=""
REGISTRY="${HARBOR_REGISTRY:-}"
PROJECT="${HARBOR_PROJECT:-}"
LOCAL_IMAGE_NAMESPACE="${RTMF_LOCAL_IMAGE_NAMESPACE:-rtmf}"
MODE="push"
PUSH_REQUESTED=false
LOCAL_BUILD=false
OUTPUT_DIR="dist/images"
LOAD=false
LOAD_EXPLICIT=false
PLATFORM="${DOCKER_PLATFORM:-}"
BUILDKIT_ADDR_ARG=""
BUILDKIT_ADDR_RESOLVED=""
DOCKER_CONFIG_ARG=""
ACTIVE_DOCKER_CONFIG=""
LATEST=false
DRY_RUN=false
SERVICES=()
BUILDCTL_CMD=()

while (($# > 0)); do
  case "$1" in
    --tag)
      (($# >= 2)) || die "--tag requires a value"
      TAG_ARG="$2"
      shift 2
      ;;
    --registry)
      (($# >= 2)) || die "--registry requires a value"
      REGISTRY="$2"
      shift 2
      ;;
    --project)
      (($# >= 2)) || die "--project requires a value"
      PROJECT="$2"
      shift 2
      ;;
    --push)
      MODE="push"
      PUSH_REQUESTED=true
      shift
      ;;
    --local-build)
      MODE="local-build"
      LOCAL_BUILD=true
      shift
      ;;
    --local-namespace)
      (($# >= 2)) || die "--local-namespace requires a value"
      LOCAL_IMAGE_NAMESPACE="$2"
      shift 2
      ;;
    --output-dir)
      (($# >= 2)) || die "--output-dir requires a value"
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --load)
      LOAD=true
      LOAD_EXPLICIT=true
      shift
      ;;
    --no-load)
      LOAD=false
      LOAD_EXPLICIT=true
      shift
      ;;
    --platform)
      (($# >= 2)) || die "--platform requires a value"
      PLATFORM="$2"
      shift 2
      ;;
    --buildkit-addr)
      (($# >= 2)) || die "--buildkit-addr requires a value"
      BUILDKIT_ADDR_ARG="$2"
      shift 2
      ;;
    --docker-config)
      (($# >= 2)) || die "--docker-config requires a value"
      DOCKER_CONFIG_ARG="$2"
      shift 2
      ;;
    --latest)
      LATEST=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    --*)
      die "unknown option: $1"
      ;;
    *)
      SERVICES+=("$1")
      shift
      ;;
  esac
done

if [[ "$PUSH_REQUESTED" == true && "$LOCAL_BUILD" == true ]]; then
  die "--push and --local-build cannot be used together"
fi

if [[ "$MODE" == push && "$LOAD_EXPLICIT" == true ]]; then
  if [[ "$LOAD" == true ]]; then
    if [[ "$PUSH_REQUESTED" == true ]]; then
      die "--push and --load cannot be used together"
    fi
    die "--load requires --local-build"
  fi
  die "--no-load is valid only with --local-build"
fi

if [[ "$MODE" != local-build && "$LOAD" == true ]]; then
  die "--load requires --local-build"
fi

if [[ "$MODE" == local-build && "$LATEST" == true ]]; then
  die "--latest is supported only in push mode"
fi

if [[ "$MODE" == local-build && -z "${LOCAL_IMAGE_NAMESPACE%/}" ]]; then
  die "local image namespace cannot be empty"
fi

if [[ -n "$PLATFORM" && "$PLATFORM" == *,* ]]; then
  if [[ "$MODE" == local-build ]]; then
    die "multi-platform local-build is not supported"
  fi
  die "multi-platform push is not supported by this script yet"
fi

if [[ "$MODE" == push ]]; then
  if [[ -z "$REGISTRY" || -z "$PROJECT" ]]; then
    die "push mode requires --registry ... --project ... or HARBOR_REGISTRY/HARBOR_PROJECT. Use --local-build for local development archives."
  fi
  validate_harbor_registry "$REGISTRY"
  if [[ -n "$REGISTRY" && -z "$PROJECT" ]]; then
    die "registry was provided but project is empty"
  fi
  if [[ -z "$REGISTRY" && -n "$PROJECT" ]]; then
    die "project was provided but registry is empty"
  fi
fi

if [[ ${#SERVICES[@]} -eq 0 ]]; then
  SERVICES=("${DEFAULT_SERVICES[@]}")
fi

resolve_tag

for service in "${SERVICES[@]}"; do
  validate_service "$service"
done

if ! command -v buildctl >/dev/null 2>&1; then
  die "buildctl is required but was not found on PATH"
fi

if [[ "$MODE" == local-build && "$LOAD" == true ]]; then
  if ! command -v docker >/dev/null 2>&1; then
    die "docker CLI is required for --load but was not found on PATH"
  fi
fi

resolve_buildkit_addr

if [[ "$MODE" == push ]]; then
  prepare_docker_config
fi

if [[ "$MODE" == local-build && "$DRY_RUN" == false ]]; then
  mkdir -p "$OUTPUT_DIR"
fi

echo "Repository root: $ROOT_DIR"
echo "Mode: $MODE"
echo "BuildKit addr: $BUILDKIT_ADDR_RESOLVED"
echo "Image tag: $IMAGE_TAG"
if [[ -n "$PLATFORM" ]]; then
  echo "Platform: $PLATFORM"
fi
if [[ "$MODE" == push ]]; then
  echo "Registry/project: ${REGISTRY%/}/${PROJECT#/}"
  echo "Docker config: $ACTIVE_DOCKER_CONFIG"
else
  echo "Output dir: $OUTPUT_DIR"
  echo "Load after build: $LOAD"
  echo "Local image namespace: ${LOCAL_IMAGE_NAMESPACE%/}"
fi
echo "Services: ${SERVICES[*]}"
echo

echo "Image refs:"
for service in "${SERVICES[@]}"; do
  if [[ "$MODE" == push ]]; then
    echo "  $service -> $(harbor_image_ref_for_service "$service" "$REGISTRY" "$PROJECT" "$IMAGE_TAG")"
    if [[ "$LATEST" == true ]]; then
      echo "  $service -> $(harbor_image_ref_for_service "$service" "$REGISTRY" "$PROJECT" latest)"
    fi
  else
    echo "  $service -> $(local_image_ref_for_service "$service" "$IMAGE_TAG")"
  fi
done
echo

for service in "${SERVICES[@]}"; do
  if [[ "$MODE" == push ]]; then
    build_service_push "$service" "$(harbor_image_ref_for_service "$service" "$REGISTRY" "$PROJECT" "$IMAGE_TAG")"
    if [[ "$LATEST" == true ]]; then
      build_service_push "$service" "$(harbor_image_ref_for_service "$service" "$REGISTRY" "$PROJECT" latest)"
    fi
  else
    build_service_local "$service" "$(local_image_ref_for_service "$service" "$IMAGE_TAG")"
  fi
done
