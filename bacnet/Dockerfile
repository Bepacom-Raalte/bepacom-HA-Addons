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
    rust \

  && apk add --update py3-pip --no-cache \

  && pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir \
    justpy \
    bacpypes \
    flask

WORKDIR /

COPY rootfs /