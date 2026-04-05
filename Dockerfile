FROM python:3.14-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md LICENSE.md ./
RUN mkdir -p boomarr && touch boomarr/__init__.py boomarr/py.typed \
    && pip install --no-cache-dir . \
    && rm -rf boomarr

COPY boomarr/ ./boomarr/
RUN pip install --no-cache-dir --no-deps .

RUN useradd --create-home --no-log-init --uid 1000 boomarr

USER boomarr

ENTRYPOINT ["boomarr"]
CMD ["--help"]
