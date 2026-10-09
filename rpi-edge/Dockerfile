# Debian trixie + the Raspberry Pi apt repo: the libcamera/picamera2 Python bindings only
# exist as system packages (built for the system Python), they cannot be installed from PyPI.
#
# The base images are pinned by digest. With floating tags (debian:trixie-slim, uv:latest) every upstream
# update silently invalidates the whole build cache, and the apt step below is ~250 MB of downloads, which
# takes tens of minutes over a slow link. To upgrade on purpose, replace the digests:
#   docker buildx imagetools inspect debian:trixie-slim
#   docker buildx imagetools inspect ghcr.io/astral-sh/uv:latest
FROM debian:trixie-slim@sha256:a29215f6a35e51e22adffa17f89e9d2ef06214e64a2bad10d765c46aea49f11f

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never

# The key is vendored (copied from the raspberrypi-archive-keyring package): the one served at
# archive.raspberrypi.com/debian/raspberrypi.gpg.key is SHA1-signed and rejected by apt on trixie.
COPY raspberrypi-archive-keyring.pgp /usr/share/keyrings/raspberrypi-archive-keyring.pgp
RUN echo "deb [signed-by=/usr/share/keyrings/raspberrypi-archive-keyring.pgp] http://archive.raspberrypi.com/debian/ trixie main" \
        > /etc/apt/sources.list.d/raspi.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-dev build-essential swig liblgpio-dev python3-picamera2 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a /uv /uvx /bin/

WORKDIR /app

# --system-site-packages so the venv sees the apt-installed picamera2/libcamera
RUN uv venv --system-site-packages --python /usr/bin/python3 /opt/venv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

CMD ["/opt/venv/bin/python", "main.py"]
