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
    py3-packaging \

  && pip install --no-cache-dir --only-binary bacpypes \
    flask \
    nicegui

WORKDIR /

COPY rootfs /