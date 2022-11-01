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

  && pip install --no-cache-dir --upgrade pip\
    setuptools \
    bacpypes \
    matplotlib \
    flask

WORKDIR /

COPY rootfs /