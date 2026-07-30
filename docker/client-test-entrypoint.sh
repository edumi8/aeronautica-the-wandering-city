#!/bin/sh
# Starts Xvfb and waits for its actual X11 socket to appear before exec'ing
# the real command, instead of relying on `xvfb-run`'s own readiness
# detection -- confirmed hanging indefinitely in this container runtime
# (Xvfb itself was up and healthy, but `xvfb-run` never proceeded past its
# wait loop). Checking for the socket file directly is the same technique
# xvfb-run itself uses internally, just without whatever is causing it to
# never observe success here.
set -e

DISPLAY_NUM=99
Xvfb ":${DISPLAY_NUM}" -screen 0 1280x720x24 -nolisten tcp &

for _ in $(seq 1 60); do
    if [ -e "/tmp/.X11-unix/X${DISPLAY_NUM}" ]; then
        break
    fi
    sleep 0.5
done

if [ ! -e "/tmp/.X11-unix/X${DISPLAY_NUM}" ]; then
    echo "ERROR: Xvfb did not create its X11 socket within 30s" >&2
    exit 1
fi

export DISPLAY=":${DISPLAY_NUM}"
exec "$@"
