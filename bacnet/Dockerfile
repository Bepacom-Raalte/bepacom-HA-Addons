# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

USER root 

# Install requirements for add-on
WORKDIR /usr/src
RUN \
  apk add --no-cache \
    iproute2 \
    nginx \
    nmap \
    python3 \
    py3-pip \
    py3-setuptools \
    py3-wheel \
  && pip3 install --no-cache-dir --upgrade pip\
    bacpypes \
    flask \
    fastapi \
    zeroconf \
    uvicorn[standard] \
    websockets

WORKDIR /


COPY rootfs /