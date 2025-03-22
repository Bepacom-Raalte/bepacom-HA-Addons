ARG BUILD_FROM
FROM ${BUILD_FROM}

# Install requirements for add-on
WORKDIR /usr/src
RUN \
  apk add --no-cache \
    nginx \
    python3 \
    py3-pip \
    py3-setuptools \
    py3-wheel \
  && pip3 install --no-cache-dir --upgrade pip \
    'bacpypes3<=0.0.102' \
    'pydantic<=2.10.6' \
    'fastapi<=0.115.11' \
    'jinja2<=3.1.6' \
    'uvicorn<=0.34.0' \
    'websockets<=15.0.1' \
    'python-multipart<=0.0.20' \
    'requests<=2.32.3 ' \
    'backoff<=2.2.1' \
    'sqlitedict<=2.1.0' \
    'psutil<=7.0.0'

WORKDIR /

COPY rootfs /

LABEL \
    io.hass.name="${BUILD_NAME}" \
    io.hass.description="${BUILD_DESCRIPTION}" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version=${BUILD_VERSION} \
    maintainer="Bepacom B.V. <lgeertsema@bepacom.nl>" \
    org.opencontainers.image.title="${BUILD_NAME}" \
    org.opencontainers.image.description="${BUILD_DESCRIPTION}" \
    org.opencontainers.image.vendor="Bepacom B.V." \
    org.opencontainers.image.authors="Bepacom B.V. <lgeertsema@bepacom.nl>" \
    org.opencontainers.image.licenses="Apache-2.0" \
    org.opencontainers.image.url="https://github.com/Bepacom-Raalte/bepacom-HA-Addons" \
    org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \
    org.opencontainers.image.created=${BUILD_DATE} \
    org.opencontainers.image.revision=${BUILD_REF} \
    org.opencontainers.image.version=${BUILD_VERSION}