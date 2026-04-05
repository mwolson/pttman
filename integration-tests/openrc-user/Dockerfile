FROM alpine:3.21

RUN echo "https://dl-cdn.alpinelinux.org/alpine/edge/main" >> /etc/apk/repositories && \
    apk update && \
    apk add --no-cache bash openrc python3 procps

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create non-root test user
RUN adduser -D -u 1000 testuser

# Install pttman as testuser (matches uv tool install workflow)
COPY README.md pyproject.toml /build/
COPY pttman/ /build/pttman/
COPY systemd/ /build/systemd/
COPY openrc-system/ /build/openrc-system/
COPY openrc-user/ /build/openrc-user/
RUN su testuser -s /bin/sh -c 'uv tool install /build/'

COPY integration-tests/shared/fake-pactl /usr/local/bin/pactl
RUN chmod +x /usr/local/bin/pactl

COPY integration-tests/openrc-user/test.sh /opt/test.sh
RUN chmod +x /opt/test.sh

CMD ["/opt/test.sh"]
