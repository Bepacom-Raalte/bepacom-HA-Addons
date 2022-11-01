# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

# Install requirements for add-on
WORKDIR /usr/src
RUN \
  apk add --no-cache \
    nginx \
    nmap \
    python3 \
    python3-dev \
    py3-pip \
    py3-wheel \
    py3-setuptools \
    py3-matplotlib 

RUN pip install --no-cache-dir --upgrade pip\
    bacpypes \
    flask

RUN pip install --no-cache-dir nicegui 

WORKDIR /

COPY rootfs /