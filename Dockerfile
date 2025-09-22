FROM apache/airflow:2.8.1

USER root

# Change the default shell to a more standard one
SHELL ["/bin/bash", "-c"]

# Update package lists
RUN apt-get update

# Install dependencies including chromium
RUN apt-get install -y --no-install-recommends \
    chromium-browser \
    && rm -rf /var/lib/apt/lists/*

USER airflow

COPY requirements.txt /
RUN pip install --no-cache-dir -r /requirements.txt