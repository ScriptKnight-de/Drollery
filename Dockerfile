FROM python:3.12-slim

ARG WITH_TESSERACT=0
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && if [ "$WITH_TESSERACT" = "1" ]; then apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-deu; fi \
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
