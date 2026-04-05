FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV container=docker

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        dbus \
        dbus-user-session \
        procps \
        python3 \
        systemd \
        systemd-sysv \
    && rm -rf /var/lib/apt/lists/*

# Remove unnecessary systemd units to speed up boot
RUN rm -f /lib/systemd/system/multi-user.target.wants/* \
    /etc/systemd/system/*.wants/* \
    /lib/systemd/system/local-fs.target.wants/* \
    /lib/systemd/system/sockets.target.wants/*udev* \
    /lib/systemd/system/sockets.target.wants/*initctl* \
    /lib/systemd/system/sysinit.target.wants/systemd-tmpfiles-setup* \
    /lib/systemd/system/systemd-update-utmp*

# Create non-root test user and enable lingering so systemd starts user@1000.service
RUN useradd -m -u 1000 testuser && \
    mkdir -p /var/lib/systemd/linger && touch /var/lib/systemd/linger/testuser

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install pttman as testuser (matches uv tool install workflow)
COPY README.md pyproject.toml /build/
COPY pttman/ /build/pttman/
COPY systemd/ /build/systemd/
COPY openrc-system/ /build/openrc-system/
COPY openrc-user/ /build/openrc-user/
RUN su testuser -s /bin/sh -c 'uv tool install /build/'

COPY integration-tests/shared/fake-pactl /usr/local/bin/pactl
RUN chmod +x /usr/local/bin/pactl

COPY integration-tests/systemd/test.sh /opt/test.sh
RUN chmod +x /opt/test.sh

STOPSIGNAL SIGRTMIN+3
CMD ["/lib/systemd/systemd"]
