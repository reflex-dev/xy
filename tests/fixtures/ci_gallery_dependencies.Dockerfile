# Reproduce the hosted Ubuntu baseline for the offline installer test.
# Build context contains only this file and the committed lock as lock.json.
FROM ubuntu@sha256:24737cef17f4e22b1977df7d9a05e77c4e28b7da5b8911f8d8ccda136bf3573c
RUN apt-get -o Acquire::http::Timeout=20 -o Acquire::Retries=1 update \
    && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::http::Timeout=20 -o Acquire::Retries=1 install --no-install-recommends -y ffmpeg python3 sudo
COPY lock.json /lock.json
RUN python3 -c 'import json, subprocess; names = [p["name"] for p in json.load(open("/lock.json"))["packages"]]; subprocess.run(["apt-get", "remove", "--yes", *names], check=True)' \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb \
    && ! command -v ffmpeg
