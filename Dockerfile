FROM apache/airflow:2.8.1

USER root

# Install Chromium for ARM architecture
RUN apt-get update && \
    apt-get install -y --no-install-recommends chromium-browser && \
    rm -rf /var/lib/apt/lists/*

USER airflow

COPY requirements.txt /
RUN pip install --no-cache-dir -r /requirements.txt