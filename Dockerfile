# Skullstrip Bench as a container: the Python tool plus Apptainer, so that it
# can launch the skull-stripping containers itself (Apptainer nested in
# Apptainer). Built once on a machine with internet; nothing is downloaded
# when it runs. See README, "The tool's own container".
#
#   invoke build-image          # docker build + docker save → skullstrip-bench_<version>.tar
#   apptainer build skullstrip-bench.sif docker-archive://skullstrip-bench_<version>.tar
FROM --platform=linux/amd64 ubuntu:24.04

# Every download goes over https: some networks throttle plain-http Ubuntu
# mirrors to a standstill. apt needs CA certificates to speak https, and the
# base image has none, so they are copied from an image that has them.
ARG APPTAINER_VERSION=1.5.4
COPY --from=buildpack-deps:noble-curl /etc/ssl/certs /etc/ssl/certs
ADD https://github.com/apptainer/apptainer/releases/download/v${APPTAINER_VERSION}/apptainer_${APPTAINER_VERSION}_amd64.deb /tmp/apptainer.deb
ENV DEBIAN_FRONTEND=noninteractive
RUN sed -i 's|http://|https://|g' /etc/apt/sources.list.d/ubuntu.sources \
 && apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates git python3 /tmp/apptainer.deb \
 && rm -rf /var/lib/apt/lists/* /tmp/apptainer.deb

# Python environment, pinned by uv.lock (no dev tools).
COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /usr/local/bin/uv
WORKDIR /opt/skullstrip-bench
COPY pyproject.toml uv.lock ./
RUN UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --frozen --no-dev --no-install-project \
        --python /usr/bin/python3 \
 && rm -rf /root/.cache

# The project itself: code, tool configs and the tools' bundled requirements
# (no data, no outputs).
COPY tasks.py invoke.yaml ./
COPY analysis ./analysis
COPY tools ./tools
COPY container_requirements ./container_requirements
ARG VERSION=unknown
RUN echo "$VERSION" > VERSION
COPY container/skullstrip-bench /usr/local/bin/skullstrip-bench

ENV PATH=/opt/venv/bin:$PATH \
    SKULLSTRIP_BENCH_IN_CONTAINER=1 \
    MPLCONFIGDIR=/tmp/matplotlib
ENTRYPOINT ["skullstrip-bench"]
