# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

# Install requirements for add-on
WORKDIR /usr/src
RUN \
  apk add --no-cache \
    python3
    nginx \
    pwgen \

RUN \
  apk add --update py3-pip --no-cache

RUN pip install --no-cache-dir --upgrade pip

RUN pip install --no-cache-dir --upgrade bacpypes flask

WORKDIR /

COPY rootfs /