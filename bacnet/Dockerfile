# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM


# Install requirements for add-on
WORKDIR /usr/src
RUN \
  apk add --no-cache \
    nginx \
    gcompat \
    nmap \
    make \
    build-base \
    python3 \
    py3-pip \
    python3-dev \
    py3-setuptools \
    py3-wheel \
    py3-numpy \
    py3-matplotlib 



RUN pip install --no-cache-dir --upgrade pip\
    bacpypes \
    flask 
    
RUN pip install --no-cache-dir \
    contourpy \
    cycler \
    python-dateutil \
    fontTools \
    kiwisolver \
    Numpy \
    packaging \
    Pillow \
    pyparsing \
    setuptools

RUN pip install --no-cache-dir --prefer-binary matplotlib 

RUN pip install --no-cache-dir nicegui 

WORKDIR /

COPY rootfs /