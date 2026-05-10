FROM rust:1.95-alpine AS builder

RUN apk add --no-cache musl-dev
WORKDIR /build
COPY . .
RUN cargo install --path . --locked --root /out

FROM alpine:3.21

RUN echo "https://dl-cdn.alpinelinux.org/alpine/edge/main" >> /etc/apk/repositories && \
    apk update && \
    apk add --no-cache bash openrc procps

RUN adduser -D -u 1000 testuser

COPY --from=builder /out/bin/pttman /usr/local/bin/pttman
COPY integration-tests/shared/fake-pactl /usr/local/bin/pactl
RUN chmod +x /usr/local/bin/pactl

COPY integration-tests/openrc-user/test.sh /opt/test.sh
RUN chmod +x /opt/test.sh

CMD ["/opt/test.sh"]
