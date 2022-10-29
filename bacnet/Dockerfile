# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

# Install requirements for add-on
WORKDIR /usr/src
RUN \
  apk add --no-cache \
    python3 \
    nginx -with-debug \
    pwgen \
    nmap \

  && apk add --update py3-pip --no-cache \

  && pip install --no-cache-dir \
    pip \
    bacpypes \
    flask

WORKDIR /

COPY rootfs /