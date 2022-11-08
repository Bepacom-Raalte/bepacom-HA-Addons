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
    py3-pip \
    py3-setuptools \
    py3-wheel \
  && pip3 install --no-cache-dir --upgrade pip\
    bacpypes \
    flask \
    fastapi \
    zeroconf \
    uvicorn 

WORKDIR /

RUN sysctl -w net.ipv4.icmp_echo_ignore_broadcasts=0

COPY rootfs /