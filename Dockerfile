FROM apache/airflow:2.8.1

USER root

# Set ARG for architecture
ARG TARGETARCH

# Install browser based on architecture
RUN apt-get update && \
    if [ "$TARGETARCH" = "arm64" ]; then \
        apt-get install -y --no-install-recommends chromium chromium-driver; \
    else \
        apt-get install -y --no-install-recommends wget gnupg && \
        wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - && \
        sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list' && \
        apt-get update && \
        apt-get install -y --no-install-recommends google-chrome-stable; \
    fi && \
    rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y     libgstreamer1.0-0     gstreamer1.0-plugins-base     gstreamer1.0-plugins-good     gstreamer1.0-plugins-bad     libwoff1     libvpx7     libevent-2.1-7     libsecret-1-0     libenchant-2-2     libhyphen0     libmanette-0.2-0     flite     libgles2     libx264-164     libwebpdemux2     libharfbuzz-icu0 &&     rm -rf /var/lib/apt/lists/*
USER airflow

COPY requirements.txt /
RUN pip install --no-cache-dir -r /requirements.txt
RUN playwright install
