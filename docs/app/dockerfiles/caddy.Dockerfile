FROM caddy:2-alpine

RUN apk add --no-cache unzip

COPY frontend.zip /tmp/frontend.zip

RUN rm -rf /usr/share/caddy/* && \
    unzip -q /tmp/frontend.zip -d /usr/share/caddy && \
    rm /tmp/frontend.zip && \
    chmod -R 755 /usr/share/caddy
