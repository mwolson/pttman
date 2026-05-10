FROM rust:1.95-bookworm AS builder

WORKDIR /build
COPY . .
RUN cargo install --path . --locked --root /out

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV container=docker

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        dbus \
        dbus-user-session \
        procps \
        systemd \
        systemd-sysv \
    && rm -rf /var/lib/apt/lists/*

RUN rm -f /lib/systemd/system/multi-user.target.wants/* \
    /etc/systemd/system/*.wants/* \
    /lib/systemd/system/local-fs.target.wants/* \
    /lib/systemd/system/sockets.target.wants/*udev* \
    /lib/systemd/system/sockets.target.wants/*initctl* \
    /lib/systemd/system/sysinit.target.wants/systemd-tmpfiles-setup* \
    /lib/systemd/system/systemd-update-utmp*

RUN useradd -m -u 1000 testuser && \
    mkdir -p /var/lib/systemd/linger && touch /var/lib/systemd/linger/testuser

COPY --from=builder /out/bin/pttman /usr/local/bin/pttman
COPY integration-tests/shared/fake-pactl /usr/local/bin/pactl
RUN chmod +x /usr/local/bin/pactl

COPY integration-tests/systemd/test.sh /opt/test.sh
RUN chmod +x /opt/test.sh

STOPSIGNAL SIGRTMIN+3
CMD ["/lib/systemd/systemd"]
