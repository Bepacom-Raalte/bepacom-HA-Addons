ARG BUILD_FROM=ghcr.io/hassio-addons/base:13.0.0
# hadolint ignore=DL3006
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
  && pip3 install --no-cache-dir --upgrade pip\
    bacpypes>=0.18.6 \
    fastapi>=0.92.0 \
    jinja2>=3.1.2 \
    uvicorn>=0.20.0 \
    websockets>=10.4

WORKDIR /

COPY rootfs /
