# syntax=docker/dockerfile:1
#
# Parameterized Java addon base.
# - Adds a simulator Java runtime (SIM_JAVA) without clobbering executor Java.
# - Installs the simulator runtime under /opt/java<SIM_JAVA>.
#
# Build example:
#   ./docker/build.sh --dockerfile docker/java/Dockerfile \
#     --technology java-21 \
#     --build-arg SIM_JAVA=21 \
#     --build-arg BASE_IMAGE=worker-executor-0.1.0-base
#
# Simulator usage:
#   /usr/local/bin/java21 -version
#   echo "$SIMULATOR_JAVA_HOME"
#   /opt/simulator/java/bin/java -version

ARG BASE_IMAGE=ubuntu:24.04
ARG SIM_JAVA=21

FROM eclipse-temurin:${SIM_JAVA}-jre AS javasrc
ARG SIM_JAVA

# Resolve runtime directory from source image into a stable staging location.
RUN set -eux; \
    JAVA_BIN="$(command -v java)"; \
    JAVA_BIN_REAL="$(readlink -f "${JAVA_BIN}")"; \
    JAVA_HOME_SRC="$(dirname "$(dirname "${JAVA_BIN_REAL}")")"; \
    mkdir -p /java-runtime; \
    cp -a "${JAVA_HOME_SRC}/." /java-runtime/

FROM ${BASE_IMAGE} AS final
ARG SIM_JAVA

# Copy Java runtime into a versioned prefix to avoid clobbering executor Java
COPY --from=javasrc /java-runtime /opt/java${SIM_JAVA}

ENV SIMULATOR_JAVA_HOME=/opt/java${SIM_JAVA}

RUN set -eux; \
    mkdir -p /usr/local/bin /opt/simulator; \
    ln -sf "/opt/java${SIM_JAVA}/bin/java" "/usr/local/bin/java${SIM_JAVA}"; \
    if [ -x "/opt/java${SIM_JAVA}/bin/javac" ]; then \
      ln -sf "/opt/java${SIM_JAVA}/bin/javac" "/usr/local/bin/javac${SIM_JAVA}"; \
    fi; \
    if [ -x "/opt/java${SIM_JAVA}/bin/jar" ]; then \
      ln -sf "/opt/java${SIM_JAVA}/bin/jar" "/usr/local/bin/jar${SIM_JAVA}"; \
    fi; \
    ln -sfn "/opt/java${SIM_JAVA}" /opt/simulator/java; \
    conf="/etc/ld.so.conf.d/java${SIM_JAVA}.conf"; \
    : > "${conf}"; \
    if [ -d "/opt/java${SIM_JAVA}/lib" ]; then \
      echo "/opt/java${SIM_JAVA}/lib" >> "${conf}"; \
    fi; \
    if [ -d "/opt/java${SIM_JAVA}/lib/server" ]; then \
      echo "/opt/java${SIM_JAVA}/lib/server" >> "${conf}"; \
    fi; \
    if [ -s "${conf}" ] && command -v ldconfig >/dev/null 2>&1; then \
      ldconfig; \
    else \
      rm -f "${conf}"; \
    fi; \
    "/usr/local/bin/java${SIM_JAVA}" -version

# Entrypoint inherited from base image
