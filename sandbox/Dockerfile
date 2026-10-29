FROM node:22-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da AS node
FROM python:3.15.0-slim-bookworm@sha256:0e019bbdfb5d9874cb2389f1c2884b64aa2ac97c99960b5bc521cef978c0617d
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
# Replace the base image's npm 10 bundle, whose dependencies have known high
# advisories. Verify the published tarball before executing the installer.
RUN python -c "import base64,hashlib,pathlib,urllib.request; data=urllib.request.urlopen('https://registry.npmjs.org/npm/-/npm-12.2.1.tgz',timeout=30).read(); assert base64.b64encode(hashlib.sha512(data).digest()).decode() == 'bKCmFRVT/BB+YPEYbZwQ1XUI3N5t4xKSpU1MxOjo7z3iWzKBJ0ZXRC1xFdEN+TC7N5TdywaBzf2dMXGJq/e2PQ=='; pathlib.Path('/tmp/npm.tgz').write_bytes(data)" \
    && npm install --global /tmp/npm.tgz --omit=dev --ignore-scripts \
    && npm cache clean --force && rm /tmp/npm.tgz
COPY patch_npm.py /tmp/prism-patch-npm.py
RUN python /tmp/prism-patch-npm.py && rm /tmp/prism-patch-npm.py \
    && npm --version \
    && node -e "require('/usr/local/lib/node_modules/npm/node_modules/undici')"
COPY requirements.lock /tmp/prism-requirements.lock
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --require-hashes -r /tmp/prism-requirements.lock \
    && rm /tmp/prism-requirements.lock
ENV HOME=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /workspace
USER 65534:65534
CMD ["python", "--version"]
