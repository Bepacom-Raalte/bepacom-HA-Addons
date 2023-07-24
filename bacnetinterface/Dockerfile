ARG BUILD_FROM
FROM ${BUILD_FROM}

COPY requirements.txt /usr/src/requirements.txt

# Install requirements for add-on
WORKDIR /usr/src
RUN \
  apk add --no-cache \
    nginx \
    python3 \
    py3-pip \
    py3-setuptools \
    py3-wheel \
  && pip3 install --no-cache-dir --upgrade pip \
  -r requirements.txt

WORKDIR /

COPY rootfs /
