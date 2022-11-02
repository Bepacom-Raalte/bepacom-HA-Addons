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
    py3-setuptools \
    py3-wheels \
    py3-packaging \
    py3-matplotlib \

  && pip install --no-cache-dir bacpypes \
    flask \
    nicegui

WORKDIR /

COPY rootfs /