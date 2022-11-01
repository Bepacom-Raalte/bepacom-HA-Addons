# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

# Install requirements for add-on
WORKDIR /usr/src
RUN \
  apk add --no-cache \
    python3 \
    nginx \
    nmap \
    py3-pip \
    py3-wheel \
    py3-setuptools \
    py3-matplotlib \

  && pip install --no-cache-dir --upgrade pip\
    bacpypes \
    nicegui \
    flask

WORKDIR /

COPY rootfs /