FROM apache/airflow:2.8.1

USER root

# Change the default shell to a more standard one
SHELL ["/bin/bash", "-c"]

# Overwrite sources.list to use standard Debian repositories, then update
RUN echo "deb http://deb.debian.org/debian bullseye main" > /etc/apt/sources.list && \
    echo "deb http://deb.debian.org/debian bullseye-updates main" >> /etc/apt/sources.list && \
    echo "deb http://security.debian.org/debian-security bullseye-security main" >> /etc/apt/sources.list && \
    apt-get update

# Install dependencies including chromium
RUN apt-get install -y --no-install-recommends \
    chromium-browser \
    && rm -rf /var/lib/apt/lists/*

USER airflow

COPY requirements.txt /
RUN pip install --no-cache-dir -r /requirements.txt
