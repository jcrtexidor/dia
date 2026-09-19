FROM ubuntu:26.04@sha256:da6fc2be547864451aa253836dd926da33623312df4a9a243e35dc877c378a78

ARG DEBIAN_FRONTEND=noninteractive
ARG BUILD_JOBS=4
ARG XPM_PIXBUF_REVISION=d290a0c846687b22d2a8c5aaec83a6689f30e1c3
ARG PYTEST_VERSION=9.1.1

RUN apt-get update && apt-get install -y --no-install-recommends \
      appstream \
      build-essential \
      ca-certificates \
      dbus-x11 \
      desktop-file-utils \
      fonts-dejavu-core \
      gettext \
      gir1.2-gtk-3.0 \
      git \
      libcairo2-dev \
      libgraphene-1.0-dev \
      libgtk-3-dev \
      librsvg2-common \
      libxml2-dev \
      libxml2-utils \
      libxslt1-dev \
      meson \
      ninja-build \
      pkg-config \
      python3-dev \
      python3-gi \
      python3-gi-cairo \
      python3-venv \
      shared-mime-info \
      xauth \
      xvfb \
    && rm -rf /var/lib/apt/lists/*

# The SDK lives outside Ubuntu's externally managed system Python. Dia embeds
# the system Python; system-site-packages also makes apt's PyGObject available
# when running validation tools from the virtual environment.
COPY mcp/requirements.lock /tmp/dia-mcp-requirements.lock
RUN python3 -m venv --system-site-packages /opt/dia-mcp-venv \
    && /opt/dia-mcp-venv/bin/pip install --no-cache-dir \
      --require-hashes -r /tmp/dia-mcp-requirements.lock \
    && /opt/dia-mcp-venv/bin/pip install --no-cache-dir "pytest==${PYTEST_VERSION}"

COPY . /src/dia
WORKDIR /src/dia

# Pin only the build copy: upstream's wrap continues to track main in the repo.
RUN sed -i "s/^revision = .*/revision = ${XPM_PIXBUF_REVISION}/" \
      subprojects/xpm-pixbuf.wrap \
    && meson setup /opt/dia-build \
      --prefix=/opt/dia --libdir=lib -Ddoc=disabled -Dtests=true \
    && meson compile -C /opt/dia-build -j "${BUILD_JOBS}" \
    && xvfb-run -a meson test -C /opt/dia-build --print-errorlogs \
    && meson install -C /opt/dia-build \
    && printf '%s\n' /opt/dia/lib > /etc/ld.so.conf.d/dia.conf \
    && ldconfig

ENV PATH="/opt/dia-mcp-venv/bin:/opt/dia/bin:${PATH}"
ENV NO_AT_BRIDGE=1

RUN pip install --no-cache-dir --no-deps ./mcp \
    && DIA_MCP_NATIVE=1 xvfb-run -a python -m pytest -q \
      -p no:cacheprovider /src/dia/mcp/tests \
    && python -m pip check

WORKDIR /workspace
CMD ["xvfb-run", "-a", "dia-mcp", "--workspace", "/workspace"]
