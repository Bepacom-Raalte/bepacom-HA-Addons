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
    'bacpypes3<=0.0.79' \
    'pydantic<=1.10.12' \
    'fastapi<=0.104.1' \
    'jinja2<=3.1.2' \
    'uvicorn<=0.24.0' \
    'websockets<=12.0' \
    'python-multipart<=0.0.6'

WORKDIR /

COPY rootfs /