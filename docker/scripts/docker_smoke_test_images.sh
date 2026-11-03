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
)

IMAGE_TAG="${RTMF_IMAGE_TAG:-latest}"
LOCAL_IMAGE=true
REGISTRY="${HARBOR_REGISTRY:-}"
PROJECT="${HARBOR_PROJECT:-}"
DRY_RUN=false

usage() {
  cat <<'EOF'
Usage:
  docker/scripts/docker_smoke_test_images.sh [options] [service...]

Options:
  --tag TAG            Image tag. Defaults to RTMF_IMAGE_TAG or latest.
  --local-image        Use locally loaded rtmf/<image-name>:<tag> images. Default.
  --registry REGISTRY  Registry for non-local image refs. May also be HARBOR_REGISTRY.
  --project PROJECT    Registry project for non-local image refs. May also be HARBOR_PROJECT.
  --dry-run            Print docker run commands without executing.
  -h, --help           Show this help.

Examples:
  docker/scripts/docker_smoke_test_images.sh --tag dev front
  docker/scripts/docker_smoke_test_images.sh --local-image --tag dev
  docker/scripts/docker_smoke_test_images.sh --registry harbor.example.com --project rtmf --tag abc123 front
EOF
}

die() {
  echo "error: $*" >&2
  exit 2
}

image_name_for_service() {
  case "$1" in
    front) printf 'front' ;;
    analytics) printf 'analytics' ;;
    jobs_scheduler) printf 'jobs-scheduler' ;;
    matrix_generation) printf 'matrix-generation' ;;
    simulators_repository) printf 'simulators-repository' ;;
    visualization) printf 'visualization' ;;
    evaluator) printf 'evaluator' ;;
    parser) printf 'parser' ;;
    *) return 1 ;;
  esac
}

validate_service() {
  image_name_for_service "$1" >/dev/null || die "unknown service: $1"
}

image_ref_for_service() {
  local service="$1"
  local image_name
  image_name="$(image_name_for_service "$service")"

  if "$LOCAL_IMAGE"; then
    printf 'rtmf/%s:%s' "$image_name" "$IMAGE_TAG"
    return
  fi

  [[ -n "$REGISTRY" ]] || die "--registry or HARBOR_REGISTRY is required when not using --local-image"
  [[ -n "$PROJECT" ]] || die "--project or HARBOR_PROJECT is required when not using --local-image"
  printf '%s/%s/%s:%s' "$REGISTRY" "$PROJECT" "$image_name" "$IMAGE_TAG"
}

smoke_code_for_service() {
  case "$1" in
    front)
      printf '%s' 'from adapters.keycloak_identity_adapter.composition import KeycloakIdentityAdapterContainer; import use_case_contracts; from services.use_case.composition.build_usecases import build_request_usecase_api_provider; import services.front.__main__; import services.front.composition.startup; import psycopg; print("front imports ok")'
      ;;
    analytics)
      printf '%s' 'import services.analytics.__main__; import services.analytics.composition.startup; import pandas; print("analytics imports ok")'
      ;;
    jobs_scheduler)
      printf '%s' 'import services.jobs_scheduler.__main__; import services.jobs_scheduler.composition.startup; import psycopg; print("jobs_scheduler imports ok")'
      ;;
    matrix_generation)
      printf '%s' 'import services.matrix_generation.__main__; import services.matrix_generation.composition.startup; import numpy; import SALib; print("matrix_generation imports ok")'
      ;;
    simulators_repository)
      printf '%s' 'import services.simulators_repository.__main__; import services.simulators_repository.composition.startup; import psycopg; print("simulators_repository imports ok")'
      ;;
    visualization)
      printf '%s' 'import services.visualization.__main__; import services.visualization.composition.startup; import plotly; print("visualization imports ok")'
      ;;
    evaluator)
      printf '%s' 'import services.evaluator.__main__; import services.evaluator.composition.startup; print("evaluator imports ok")'
      ;;
    parser)
      printf '%s' 'import services.parser.__main__; import services.parser.composition.startup; import joblib; import sklearn; print("parser imports ok")'
      ;;
    *)
      return 1
      ;;
  esac
}

print_command() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
}

run_smoke_test() {
  local service="$1"
  local image_ref="$2"
  local code="$3"
  local cmd=(
    docker run --rm
    --entrypoint python
    "$image_ref"
    -c "$code"
  )

  echo
  echo "Smoke testing $service:"
  echo "Image: $image_ref"
  print_command "${cmd[@]}"
  if ! "$DRY_RUN"; then
    "${cmd[@]}"
  fi
}

SERVICES=()
while (($# > 0)); do
  case "$1" in
    --tag)
      (($# >= 2)) || die "--tag requires a value"
      IMAGE_TAG="$2"
      shift 2
      ;;
    --local-image)
      LOCAL_IMAGE=true
      shift
      ;;
    --registry)
      (($# >= 2)) || die "--registry requires a value"
      REGISTRY="$2"
      LOCAL_IMAGE=false
      shift 2
      ;;
    --project)
      (($# >= 2)) || die "--project requires a value"
      PROJECT="$2"
      LOCAL_IMAGE=false
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while (($# > 0)); do
        SERVICES+=("$1")
        shift
      done
      ;;
    -*)
      die "unknown option: $1"
      ;;
    *)
      SERVICES+=("$1")
      shift
      ;;
  esac
done

if ((${#SERVICES[@]} == 0)); then
  SERVICES=("${DEFAULT_SERVICES[@]}")
fi

if ! command -v docker >/dev/null 2>&1; then
  die "docker CLI is required but was not found on PATH"
fi

echo "Selected services: ${SERVICES[*]}"
echo "Image tag: $IMAGE_TAG"
if "$LOCAL_IMAGE"; then
  echo "Image mode: local loaded images"
else
  echo "Image mode: registry images"
  echo "Registry/project: $REGISTRY/$PROJECT"
fi

for service in "${SERVICES[@]}"; do
  validate_service "$service"
done

for service in "${SERVICES[@]}"; do
  run_smoke_test "$service" "$(image_ref_for_service "$service")" "$(smoke_code_for_service "$service")"
done
