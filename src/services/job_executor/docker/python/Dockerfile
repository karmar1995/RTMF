# syntax=docker/dockerfile:1
#
# Parameterized Python addon base.
# - Adds a simulator Python runtime (SIM_PY) without clobbering executor Python.
# - Creates simulator venv at /opt/simulator/.venv (WITH pip, suitable for future package installs).
#
# Build example:
#   ./docker/build.sh --dockerfile docker/python/Dockerfile \
#     --technology python-313 \
#     --build-arg SIM_PY=3.13 \
#     --build-arg BASE_IMAGE=worker-executor-0.1.0-base
#
# Simulator usage:
#   /opt/simulator/.venv/bin/python --version
#   /opt/simulator/.venv/bin/pip --version

ARG BASE_IMAGE=python:3.12-slim
ARG SIM_PY=3.13

FROM python:${SIM_PY}-slim AS pysrc

FROM ${BASE_IMAGE} AS final
ARG SIM_PY

# Copy Python runtime into a versioned prefix to avoid clobbering executor Python
COPY --from=pysrc /usr/local /opt/python${SIM_PY}

# Provide stable python binary path.
# Also add minimal /usr/local/lib links for this SIM_PY so venv/ensurepip can find bundled wheels
# (notably needed for some versions like 3.11 when relocated under /opt).
RUN ln -sf /opt/python${SIM_PY}/bin/python${SIM_PY} /usr/local/bin/python${SIM_PY} \
    && mkdir -p /usr/local/lib \
    && ln -sfn /opt/python${SIM_PY}/lib/python${SIM_PY} /usr/local/lib/python${SIM_PY} \
    && for f in /opt/python${SIM_PY}/lib/libpython${SIM_PY}*.so*; do \
         [ -e "$f" ] || continue; \
         ln -sf "$f" "/usr/local/lib/$(basename "$f")"; \
       done \
    && /usr/local/bin/python${SIM_PY} -m venv /opt/simulator/.venv

# Entrypoint inherited from base image