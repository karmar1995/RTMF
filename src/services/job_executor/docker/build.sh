#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  ./docker/build.sh --dockerfile <path> [--technology <tech>] [--build-arg KEY=VAL] [--no-push]

Options:
  --dockerfile <path>   Path to Dockerfile to build.
  --technology <tech>   Technology name for image tag (default: env JOB_EXECUTOR_TECHNOLOGY,
                        else inferred from docker/<tech>/Dockerfile, else "python").
  --build-arg KEY=VAL   Build arg passthrough (repeatable).
  --no-push             Build without pushing to registry (outputs an OCI tar).
  -h, --help            Show this help.

Notes:
- Requires rootless BuildKit (buildctl) and a running buildkitd.
- Ensure registry credentials are available (e.g., run "docker login") before pushing.
- Example: ./docker/build.sh --dockerfile docker/python/Dockerfile --technology python-313 --build-arg SIM_PY=3.13 --build-arg BASE_IMAGE=worker-executor-0.1.0-base
USAGE
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

DOCKERFILE=""
TECHNOLOGY=""
PUSH=true
BUILD_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dockerfile)
      DOCKERFILE="${2:-}"
      shift 2
      ;;
    --technology)
      TECHNOLOGY="${2:-}"
      shift 2
      ;;
    --build-arg)
      if [[ "${2:-}" != *=* ]]; then
        echo "Error: --build-arg expects KEY=VAL, got '${2:-}'" >&2
        exit 2
      fi
      BUILD_ARGS+=("${2}")
      shift 2
      ;;
    --no-push)
      PUSH=false
      shift 1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "${DOCKERFILE}" ]]; then
  echo "Error: --dockerfile is required." >&2
  usage
  exit 2
fi

if [[ ! -f "${DOCKERFILE}" ]]; then
  echo "Error: Dockerfile not found at ${DOCKERFILE}" >&2
  exit 2
fi

if ! command -v buildctl >/dev/null 2>&1; then
  echo "Error: buildctl is required but not found in PATH." >&2
  exit 2
fi

BUILDKIT_ADDR_DEFAULT="unix:///run/user/$(id -u)/buildkit/buildkitd.sock"
BUILDKIT_ADDR="${BUILDKIT_ADDR:-${BUILDKIT_ADDR_DEFAULT}}"

SOCKET_PATH="${BUILDKIT_ADDR#unix://}"
if [[ ! -S "${SOCKET_PATH}" ]]; then
  echo "Error: BuildKit socket not found at ${SOCKET_PATH}" >&2
  exit 2
fi

if [[ -z "${TECHNOLOGY}" ]]; then
  if [[ -n "${JOB_EXECUTOR_TECHNOLOGY:-}" ]]; then
    TECHNOLOGY="${JOB_EXECUTOR_TECHNOLOGY}"
  else
    case "${DOCKERFILE}" in
      docker/*/Dockerfile)
        TECHNOLOGY="${DOCKERFILE#docker/}"
        TECHNOLOGY="${TECHNOLOGY%/Dockerfile}"
        ;;
      *)
        TECHNOLOGY="python"
        ;;
    esac
  fi
fi

IMAGE_NAME="worker-${VERSION}-base-${TECHNOLOGY}"
DOCKERFILE_DIR="$(cd "$(dirname "${DOCKERFILE}")" && pwd)"

OUTPUT_SPEC=""
if [[ "${PUSH}" == "false" ]]; then
  OCI_TAR="${IMAGE_NAME}.oci.tar"
  OUTPUT_SPEC="type=oci,dest=${OCI_TAR}"
else
  if [[ -z "${HARBOR_BASE:-}" ]]; then
    echo "Error: HARBOR_BASE must be set (e.g., 172.16.237.193:80/simulators)" >&2
    exit 2
  fi
  FULL_IMAGE_REF="${HARBOR_BASE}/${IMAGE_NAME}"
  OUTPUT_SPEC="type=image,name=${FULL_IMAGE_REF},push=true"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export REG=$HARBOR_BASE
$SCRIPT_DIR/tmp_auth.sh

export DOCKER_CONFIG=/tmp/docker-config

echo "BuildKit addr: ${BUILDKIT_ADDR}"
echo "Dockerfile: ${DOCKERFILE}"
echo "Technology: ${TECHNOLOGY}"
echo "Version: ${VERSION}"
if [[ "${PUSH}" == "false" ]]; then
  echo "Output: ${OUTPUT_SPEC}"
else
  echo "Image: ${FULL_IMAGE_REF}"
fi

buildctl --addr "${BUILDKIT_ADDR}" \
  build --frontend dockerfile.v0 \
  --local context=. \
  --local dockerfile="${DOCKERFILE_DIR}" \
  --opt filename="$(basename "${DOCKERFILE}")" \
  $(for arg in "${BUILD_ARGS[@]}"; do printf -- "--opt build-arg:%s " "${arg}"; done) \
  --output "${OUTPUT_SPEC}"

if [[ "${PUSH}" == "false" ]]; then
  echo "Built ${OUTPUT_SPEC}"
else
  echo "Pushed ${FULL_IMAGE_REF}"
fi
