# syntax=docker/dockerfile:1

# ---- Stage 1: compile libultrahdr (ultrahdr_app) --------------------------
FROM alpine:3.24.4@sha256:f59abe656b692d901e184be3445e084786602108599d2a51d229c0f5a48c71bf AS uhdr-build

RUN apk add --no-cache \
        git cmake make g++ nasm pkgconf libjpeg-turbo-dev

WORKDIR /build
# Pinned to an exact commit (v2.0.2 + fixes) for reproducible, auditable builds.
ARG UHDR_COMMIT=c6fd15cdb2d05d3aaed84b817e4c4a274a4ce600
RUN git init libultrahdr \
    && git -C libultrahdr fetch --depth 1 https://github.com/google/libultrahdr.git "$UHDR_COMMIT" \
    && git -C libultrahdr checkout --detach FETCH_HEAD

RUN cmake -G "Unix Makefiles" -DUHDR_WRITE_XMP=ON \
        -S libultrahdr -B libultrahdr/build \
    && cmake --build libultrahdr/build -j"$(nproc)"

# ---- Stage 2: runtime -------------------------------------------------------
FROM python:3.11.18-alpine@sha256:7fbad8e4652eae0186429a6f26cf5b23e27e8c6fd7ac4d0cfd7a6988cdeea1e1 AS base

# apk upgrade pulls Alpine security fixes released after the base image was built.
RUN apk upgrade --no-cache \
    && apk add --no-cache exiftool libjpeg-turbo libstdc++

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
