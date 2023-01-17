# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

USER root 

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
    fastapi>=0.88.0 \
    jinja2>=3.1.2 \
    uvicorn>=0.20.0 \
    websockets>=10.4

WORKDIR /


COPY rootfs /