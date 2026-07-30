# Headless Forge client smoke-test environment (Phase 5).
#
# Provides Java 17 + Xvfb + software OpenGL (Mesa llvmpipe) so the same
# client_smoke.py module that runs directly on a GitHub Actions ubuntu
# runner can also run locally on any Docker host (including Windows, where
# there is no reliable native headless-GL route). Nothing built from this
# image is ever published; it exists purely to execute
# `python scripts/test_pipeline.py client`.
#
# noble (Ubuntu 24.04), not jammy (22.04): jammy's apt `python3` is 3.10,
# below the pipeline's Python 3.11+ floor (confirmed by a real run of this
# image on 2026-07-30 -- `test_pipeline.py` refused to start). noble ships
# Python 3.12 as `python3` with no PPA needed.
FROM eclipse-temurin:17-noble

RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    x11-utils \
    x11-apps \
    imagemagick \
    mesa-utils \
    libgl1-mesa-dri \
    libgl1 \
    libxrandr2 \
    libxtst6 \
    libxi6 \
    libxxf86vm1 \
    libopenal1 \
    ca-certificates \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

ENV LIBGL_ALWAYS_SOFTWARE=1 \
    GALLIUM_DRIVER=llvmpipe \
    DISPLAY=:99 \
    PYTHONUNBUFFERED=1

# Baked in at build time (not from the runtime-mounted repo) so the image
# doesn't need pip installs on every container start; only the requirements
# file's content affects this layer's cache key.
COPY tests/requirements.txt /tmp/aeronautica-tests-requirements.txt
# noble's Python 3.12 refuses a plain `pip install` into the system
# interpreter (PEP 668 externally-managed-environment) -- safe to override
# here since this container's Python has exactly one purpose.
RUN python3 -m pip install --no-cache-dir --break-system-packages -r /tmp/aeronautica-tests-requirements.txt

COPY docker/client-test-entrypoint.sh /usr/local/bin/client-test-entrypoint.sh
RUN chmod +x /usr/local/bin/client-test-entrypoint.sh

WORKDIR /workspace

# Not xvfb-run: confirmed (2026-07-30) to hang indefinitely in this
# container runtime even though Xvfb itself starts and is healthy -- see
# client-test-entrypoint.sh's comment for the direct socket-based wait this
# replaces it with.
ENTRYPOINT ["/usr/local/bin/client-test-entrypoint.sh"]
CMD ["python3", "scripts/test_pipeline.py", "client", "--allow-missing-runtime"]
