# Reproduce the hosted Ubuntu baseline for the offline installer test.
# Build context contains only this file and the committed lock as lock.json.
FROM --platform=linux/amd64 ubuntu@sha256:24737cef17f4e22b1977df7d9a05e77c4e28b7da5b8911f8d8ccda136bf3573c
RUN apt-get -o Acquire::http::Timeout=20 -o Acquire::Retries=1 update \
    && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::http::Timeout=20 -o Acquire::Retries=1 install --no-install-recommends -y python3 sudo
COPY lock.json /lock.json
# Seed the runner-like baseline from the exact reviewed package versions, then
# remove the bundle. Only Ubuntu's additional baseline libraries remain.
RUN python3 -c 'import json, subprocess; packages = [p["name"] + "=" + p["version"] for p in json.load(open("/lock.json"))["packages"]]; subprocess.run(["apt-get", "-o", "Acquire::http::Timeout=20", "-o", "Acquire::Retries=1", "install", "--no-install-recommends", "--yes", *packages], check=True)'
RUN python3 -c 'import json, subprocess; names = [p["name"] for p in json.load(open("/lock.json"))["packages"]]; subprocess.run(["apt-get", "remove", "--yes", *names], check=True)' \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb \
    && ! command -v ffmpeg
