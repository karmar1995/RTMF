#!/usr/bin/env bash
set -euo pipefail

: "${REG:?REG is not set (e.g. 192.168.100.236:80)}"
: "${HARBOR_USER:?HARBOR_USER is not set (e.g. robot\$base+robot)}"
: "${HARBOR_PASS:?HARBOR_PASS is not set (robot token/password)}"

DOCKER_CFG_DIR="/tmp/docker-config"
DOCKER_CFG_PATH="${DOCKER_CFG_DIR}/config.json"

# Overwrite any existing config
rm -rf "${DOCKER_CFG_DIR}"
mkdir -p "${DOCKER_CFG_DIR}"

AUTH="$(printf '%s:%s' "$HARBOR_USER" "$HARBOR_PASS" | base64 -w0)"

cat > "${DOCKER_CFG_PATH}" <<EOF
{
  "auths": {
    "${REG}": {
      "auth": "${AUTH}",
      "username": "${HARBOR_USER}",
      "password": "${HARBOR_PASS}"
    },
    "http://${REG}": {
      "auth": "${AUTH}",
      "username": "${HARBOR_USER}",
      "password": "${HARBOR_PASS}"
    }
  }
}
EOF

chmod 600 "${DOCKER_CFG_PATH}"

echo "Wrote ${DOCKER_CFG_PATH}"
echo "Use it with: export DOCKER_CONFIG=${DOCKER_CFG_DIR}"
