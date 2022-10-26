# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

RUN echo "Trying to build"


# Install requirements for add-on
WORKDIR /usr/src
RUN \
  apk add --no-cache \
    python3

RUN \
  apk add --update py3-pip --no-cache

RUN echo "Trying to install libs"

RUN pip install --no-cache-dir --upgrade pip

RUN pip install --no-cache-dir --upgrade bacpypes flask


RUN echo "Trying to run"


WORKDIR /

COPY rootfs /