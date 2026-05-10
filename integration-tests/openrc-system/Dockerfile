FROM rust:1.95-alpine AS builder

RUN apk add --no-cache musl-dev
WORKDIR /build
COPY . .
RUN cargo install --path . --locked --root /out

FROM alpine:3.21

RUN apk add --no-cache bash openrc procps

COPY --from=builder /out/bin/pttman /usr/local/bin/pttman
COPY integration-tests/shared/fake-pactl /usr/local/bin/pactl
RUN chmod +x /usr/local/bin/pactl

COPY integration-tests/openrc-system/test.sh /opt/test.sh
RUN chmod +x /opt/test.sh

CMD ["/opt/test.sh"]
