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
    python3-dev \
    py3-setuptools \
    py3-wheel \
    py3-mathplotlib \

    && pip install --no-cache-dir pip\
    bacpypes \
    flask \
    contourpy \
    cycler \
    python-dateutil \
    fontTools \
    kiwisolver \
    packaging \
    Pillow \
    pyparsing \

    && pip install --no-cache-dir --prefer-binary -U \
        Numpy \
        mathplotlib \
    && pip install --no-cache-dir nicegui 



WORKDIR /

COPY rootfs /