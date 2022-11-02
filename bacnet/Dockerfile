# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

# Install requirements for add-on
WORKDIR /usr/src
RUN \
  apk add --no-cache \
        nginx \
        nmap \
        py3-pip \
        python3 \
    && pip3 install \
        --no-cache-dir \
        --prefer-binary \
        https://wheels.home-assistant.io/alpine-3.14/${BUILD_ARCH}/matplotlib-3.5.2-cp39-none-any.whl \
        https://wheels.home-assistant.io/alpine-3.14/${BUILD_ARCH}/numpy-1.22.0-cp38-none-any.whl \
        bacpypes \
        flask 

WORKDIR /

COPY rootfs /