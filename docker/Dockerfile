# syntax=docker/dockerfile:1

# ---- Stage 1: compile libultrahdr (ultrahdr_app) --------------------------
FROM alpine:3.24 AS uhdr-build

RUN apk add --no-cache \
        git cmake make g++ nasm pkgconf libjpeg-turbo-dev

WORKDIR /build
# Pin to a commit once you've confirmed it works for you — HEAD can move.
RUN git clone --depth 1 https://github.com/google/libultrahdr.git

RUN cmake -G "Unix Makefiles" -DUHDR_WRITE_XMP=ON \
        -S libultrahdr -B libultrahdr/build \
    && cmake --build libultrahdr/build -j"$(nproc)"

# ---- Stage 2: runtime -------------------------------------------------------
FROM python:3.11-alpine AS base

RUN apk add --no-cache exiftool libjpeg-turbo libstdc++

COPY --from=uhdr-build /build/libultrahdr/build/ultrahdr_app /usr/local/bin/ultrahdr_app
RUN chmod +x /usr/local/bin/ultrahdr_app

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY src/ src/
COPY LICENSE VERSION ./
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

FROM base AS test

RUN pip install --no-cache-dir pytest==9.1.1 pytest-cov==7.1.0
COPY pytest.ini ./
COPY tests/ tests/
CMD ["pytest", "-v"]

FROM base AS lint

RUN pip install --no-cache-dir ruff==0.16.4
COPY ruff.toml ./
COPY tests/ tests/
RUN ruff check .

FROM base

RUN adduser -D runner && mkdir -p /app/jobs && chown -R runner:runner /app
USER runner

EXPOSE 5000
ENTRYPOINT ["/app/entrypoint.sh"]
