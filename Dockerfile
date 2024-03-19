###################### START OF REQUIREMENTS GENEREATOR ######################

FROM python:3.10-slim-buster as requirements-builder


RUN pip install -U pip setuptools wheel pdm

WORKDIR /home/python/app

COPY pyproject.toml pdm.lock /home/python/app/


RUN pdm export --production -o /requirements.txt --without-hashes

###################### END OF REQUIREMENTS GENEREATOR ######################
############################# START OF BUILDER #############################
FROM python:3.10-slim-buster as builder

RUN pip install -U pip setuptools wheel

ENV PYTHONUSERBASE /home/python/app

COPY --from=requirements-builder /requirements.txt /requirements.txt

RUN pip install --isolated --no-cache-dir --user -r /requirements.txt

############################# END OF BUILDER #############################
# FROM ghcr.io/osgeo/gdal:alpine-normal-latest-amd64
# FROM python:3.10-slim-buster
FROM python:3.10-slim-bookworm

ARG VERSION
ARG NAME

USER root

# Install GDAL
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    python3-gdal && \
    rm -rf /root/.cache/pip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
    
WORKDIR /home/python/

ENV PYTHONUSERBASE /home/python/app
ENV PYTHONPATH /home/python/app
ENV NAME $NAME
ENV VERSION ${VERSION}

COPY --chown=python:python --from=builder /home/python/app /home/python/app
COPY scripts /home/python/scripts
COPY src /home/python/application
COPY spool /home/python/application/spool

WORKDIR /home/python/application

ENTRYPOINT [ "/home/python/scripts/entrypoint.sh" ]
