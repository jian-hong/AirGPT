FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt requirements.lock ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && pip install --no-cache-dir -r requirements.lock \
    && apt-get purge -y gcc libc6-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY . .

ENV AIRGPT_BIND=127.0.0.1 \
    AIRGPT_TUNNEL=0 \
    AIRGPT_NO_BROWSER=1 \
    NETIE_TOKEN_FILE=/run/netie/service-token

EXPOSE 8765

CMD ["python", "clipdrop.py"]
