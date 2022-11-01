# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

# Install requirements for add-on
WORKDIR /usr/src
RUN \
  apk add --no-cache \
    python3 \
    nginx \
    nmap 

echo "installed software, now going for libraries"

RUN apk add --update py3-pip \
  && pip install pip  \
    wheel \
    bacpypes \
    flask
    

WORKDIR /

COPY rootfs /