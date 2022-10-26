# https://developers.home-assistant.io/docs/add-ons/configuration#add-on-dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

echo "Trying to build"

# Install requirements for add-on
WORKDIR /usr/src
RUN \
  apk add --no-cache \
    python3
    py3-pip

echo "Trying to install libs"

RUN pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir -r requirements.txt


echo "Trying to run"


# Copy data for add-on
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
