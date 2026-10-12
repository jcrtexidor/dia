# Dedicated context: package.deb and package-smoke.py, never the source checkout.
FROM ubuntu:26.04@sha256:da6fc2be547864451aa253836dd926da33623312df4a9a243e35dc877c378a78
ARG DEBIAN_FRONTEND=noninteractive
ARG SMOKE_UID=1000
ARG SMOKE_GID=1000
COPY package.deb /tmp/package.deb
RUN apt-get update \
    && apt-get install -y --no-install-recommends /tmp/package.deb \
    && rm -f /tmp/package.deb \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /results \
    && chmod 1777 /results
RUN test "$SMOKE_UID" -gt 0 \
    && (getent group "$SMOKE_GID" >/dev/null || groupadd --gid "$SMOKE_GID" dia-smoke) \
    && (getent passwd "$SMOKE_UID" >/dev/null || useradd --uid "$SMOKE_UID" --gid "$SMOKE_GID" --home-dir /home/dia-smoke --shell /bin/sh dia-smoke) \
    && mkdir -p /home/dia-smoke \
    && chown "$SMOKE_UID:$SMOKE_GID" /home/dia-smoke
COPY package-smoke.py /opt/package-smoke.py
ENV PYTHONDONTWRITEBYTECODE=1
ENV HOME=/home/dia-smoke
USER ${SMOKE_UID}:${SMOKE_GID}
WORKDIR /tmp
CMD ["xvfb-run", "-a", "/opt/dia-mcp-venv/bin/python", "/opt/package-smoke.py", "--output", "/results/install-smoke.json"]
