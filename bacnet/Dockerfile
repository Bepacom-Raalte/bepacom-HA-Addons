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
    py3-wheel 


RUN pip install --no-cache-dir --upgrade pip\
    bacpypes \
    flask 
    

RUN python3 -m pip install --no-cache-dir --prefer-binary -U \
    numpy \
    matplotlib 


RUN pip install --no-cache-dir nicegui 

WORKDIR /

COPY rootfs /