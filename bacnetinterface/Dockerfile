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
    'bacpypes3<=0.0.78' \
    'fastapi<=0.100.0' \
    'jinja2<=3.1.2' \
    'uvicorn<=0.22.0' \
    'websockets<=11.0.3' \
    'python-multipart<=0.0.6'

WORKDIR /

COPY rootfs /
