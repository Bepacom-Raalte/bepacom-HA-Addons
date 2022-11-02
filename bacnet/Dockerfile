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

  && pip install --no-cache-dir --upgrade pip \
    setuptools \
    wheel \

  && pip install --no-cache-dir --prefer-binary \
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

  && pip install --no-cache-dir --only-binary -U \
    Numpy \
    mathplotlib \
  && pip install --no-cache-dir nicegui 



WORKDIR /

COPY rootfs /