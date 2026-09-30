ARG GO_IMAGE=public.ecr.aws/docker/library/golang:1.24.8-alpine
ARG RUNTIME_IMAGE=public.ecr.aws/docker/library/alpine:3.22

FROM --platform=$BUILDPLATFORM ${GO_IMAGE} AS builder

ARG TARGETOS
ARG TARGETARCH
ARG MINIO_SOURCE_REF=7aac2a2c5b7c882e68c1ce017d8256be2feea27f
ARG GO_PROXY=https://proxy.golang.org,direct
ENV CGO_ENABLED=0 \
    GOBIN=/out \
    GOPROXY=${GO_PROXY}

RUN mkdir -p /out /build \
    && cd /build \
    && go mod init smartlib-minio-build \
    && go mod download "github.com/minio/minio@${MINIO_SOURCE_REF}" \
    && MINIO_MODULE_DIR="$(find /go/pkg/mod/github.com/minio -maxdepth 1 -type d -name 'minio@*' -print -quit)" \
    && cd "$MINIO_MODULE_DIR" \
    && GOOS="$TARGETOS" GOARCH="$TARGETARCH" go build -o /out/minio . \
    && cp LICENSE /out/LICENSE \
    && printf '%s\n' "${MINIO_SOURCE_REF}" > /out/SOURCE_REF

FROM ${RUNTIME_IMAGE}

ARG MINIO_SOURCE_REF=7aac2a2c5b7c882e68c1ce017d8256be2feea27f
LABEL org.opencontainers.image.title="SmartLib MinIO Community" \
      org.opencontainers.image.description="MinIO Community compiled from the pinned upstream source" \
      org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.revision="${MINIO_SOURCE_REF}" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

RUN apk add --no-cache ca-certificates curl \
    && addgroup -S minio \
    && adduser -S -G minio -h /home/minio minio \
    && mkdir -p /data /licenses/minio \
    && chown -R minio:minio /data /home/minio

COPY --from=builder /out/minio /usr/local/bin/minio
COPY --from=builder /out/LICENSE /licenses/minio/LICENSE
COPY --from=builder /out/SOURCE_REF /licenses/minio/SOURCE_REF

USER minio
VOLUME ["/data"]
EXPOSE 9000 9001

ENTRYPOINT ["/usr/local/bin/minio"]
CMD ["server", "/data", "--console-address", ":9001"]
