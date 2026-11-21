FROM python:3.12-slim

LABEL org.opencontainers.image.title="Drollery" \
      org.opencontainers.image.description="Self-hosted library for memes, clips, sounds, albums and movies" \
      org.opencontainers.image.source="https://github.com/ScriptKnight-de/drollery" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.authors="ScriptKnight" \
      de.scriptknight.donate="https://ko-fi.com/scriptknight"

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd -u 1000 -m drollery && mkdir /data && chown drollery /data
USER drollery
ENV DROLLERY_DATA=/data HOME=/data/.home XDG_CACHE_HOME=/data/.cache
VOLUME /data
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)" || exit 1

CMD ["uvicorn", "drollery.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
