# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

RUN echo "Trying to build"


# Install requirements for add-on
WORKDIR /usr/src
RUN \
  apk add --no-cache \
    python3
    py-pip

RUN echo "Trying to install libs"

RUN pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir -r requirements.txt


RUN echo "Trying to run"

WORKDIR /rootfs
RUN for file in /etc/services.d/*/*; do \
dos2unix $file; \
chmod a+xwr $file; \
done


WORKDIR /

COPY rootfs /