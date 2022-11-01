# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

# Install requirements for add-on
WORKDIR /usr/src
RUN \
  apk add --no-cache \
    nginx \
    nmap \
    make \
    build-base \
    python3 \
    py3-pip \
    py3-mathplotlib


RUN pip install --no-cache-dir --upgrade pip\
    bacpypes \
    flask \
    mathplotlib --prefer-binary

RUN pip install --no-cache-dir nicegui 

WORKDIR /

COPY rootfs /