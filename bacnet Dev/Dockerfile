# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

USER root 

# Install requirements for add-on
WORKDIR /usr/src
RUN \
    apt-get update && apt-get install -y \
    iproute2 \
    nginx \
    nmap \
    pptpd \
    net-tools \
    tcpdump \
    python3 \
    python3-pip 

RUN \
    pip install --upgrade pip\
    bacpypes \
    flask \
    fastapi \
    uvicorn \
    websockets

WORKDIR /


COPY rootfs /