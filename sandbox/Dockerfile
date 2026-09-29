# Build from the repository root: docker build -t myagent-sandbox:1 sandbox
# Use the cached official Python image; no registry pull is required.
# For an offline build, add offline/*.deb and offline/*.whl to the build context.
# Resolve Debian dependencies against this base image and verify downloads first.
FROM python:3.12

COPY setup-runtime.sh /usr/local/bin/myagent-setup-runtime
# A read-only build mount keeps downloaded archives out of the resulting image.
RUN --mount=type=bind,target=/tmp/runtime-context \
    sh /usr/local/bin/myagent-setup-runtime /tmp/runtime-context/offline
