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
    'bacpypes3<=0.0.86' \
    'pydantic<=1.10.12' \
    'fastapi<=0.108.0' \
    'jinja2<=3.1.2' \
    'uvicorn<=0.25.0' \
    'websockets<=12.0' \
    'python-multipart<=0.0.6' \
    'requests<=2.31.0 ' \
    'backoff<=2.2.1'

WORKDIR /

COPY rootfs /

LABEL \
    io.hass.name="${BUILD_NAME}" \
    io.hass.description="${BUILD_DESCRIPTION}" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.type="addon" \
    io.hass.version=${BUILD_VERSION} \
