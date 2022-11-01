# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

# Install requirements for add-on
WORKDIR /usr/src
RUN \
  apk add --no-cache \
    python3 \
    nginx \
    pwgen \
    nmap \

  && apk add --update py3-pip \
  && pip install pip --no-cache-dir \
  && pip install wheel --no-cache-dir \
  && pip install bacpypes --no-cache-dir \
  && pip install flask --no-cache-dir 
    

WORKDIR /

COPY rootfs /