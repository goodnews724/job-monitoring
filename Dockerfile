FROM apache/airflow:2.8.1

USER root

# Set ARG for architecture
ARG TARGETARCH

# Install browser based on architecture
RUN apt-get update && \
    if [ "$TARGETARCH" = "arm64" ]; then \
        apt-get install -y --no-install-recommends chromium chromium-chromedriver; \
    else \
        apt-get install -y --no-install-recommends wget gnupg && \
        wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - && \
        sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list' && \
        apt-get update && \
        apt-get install -y --no-install-recommends google-chrome-stable; \
    fi && \
    rm -rf /var/lib/apt/lists/*

USER airflow

COPY requirements.txt /
RUN pip install --no-cache-dir -r /requirements.txt
