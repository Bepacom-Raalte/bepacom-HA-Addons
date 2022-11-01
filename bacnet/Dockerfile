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

  && apk add --update py3-pip \
  && pip install pip  \
  && pip install wheel \
  && pip install bacpypes \
  && pip install nicegui \
  && pip install flask
    

WORKDIR /

COPY rootfs /