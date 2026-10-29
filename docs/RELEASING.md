# Local releases and rollback

The release unit is an application ZIP plus the matching Linux sandbox image. Build once, retain the artifact checksum, and install that exact artifact. No production service or cloud account is created by these scripts.

## Prepare and check

Use Python 3.11 and Node 22. The complete application dependency graph is in `config/requirements/runtime.lock`; bootstrap and developer-tool graphs have their own hash locks. `config/requirements/runtime.in`, `config/requirements/bootstrap.in`, `config/requirements/tools.in`, and `sandbox/requirements.in` are resolution inputs, not installation locks.

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install --require-hashes -r config/requirements/bootstrap.lock
.venv/Scripts/python.exe -m pip install --require-hashes -r config/requirements/runtime.lock -r config/requirements/tools.lock
npm ci --prefix frontend
docker build -t prism-sandbox:local sandbox
.venv/Scripts/python.exe scripts/check.py --docker --security
```

Add `--ocr` after installing/configuring Tesseract. The check runs lint, the source credential scanner, Python/frontend tests, the production build, schema/YAML checks, dependency advisories, dependency-notice generation, and an authenticated real-server contract smoke test using a disposable workspace. It never calls a live model or captures workstation context. `scripts/model_smoke.py` is the separate opt-in real-provider check.

Scan the built sandbox before packaging:

```powershell
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock anchore/grype@sha256:621d56d1d68106b787022c81546f7e0a36202a25d1239f0c20195fab8c16f7ea prism-sandbox:local --fail-on high --only-fixed
```

This gate blocks fixable high/critical findings; it does not claim the image has no lower-severity advisories. Keep the scanner database current. Network-enabled containers use private per-action networks but still have broad network access. Review image findings and their reachability rather than suppressing the scanner to obtain a green build.

## Package

```powershell
.venv/Scripts/python.exe scripts/release.py pack --version 1.0.0-rc.1 --output .prism/dist/prism-1.0.0-rc.1.zip
.venv/Scripts/python.exe scripts/release.py verify .prism/dist/prism-1.0.0-rc.1.zip
docker save -o .prism/dist/prism-sandbox-1.0.0-rc.1.tar prism-sandbox:local
Get-FileHash .prism/dist/prism-1.0.0-rc.1.zip -Algorithm SHA256
Get-FileHash .prism/dist/prism-sandbox-1.0.0-rc.1.tar -Algorithm SHA256
```

The ZIP contains an allowlisted source tree, built frontend, notices, locks, and a deterministic manifest with file hashes, source-tree identity, version, and sandbox image ID. It excludes `.env`, installed environments, runtime state, reference checkouts, and the user's working project. Existing output paths are never overwritten. The matching sandbox image can be compressed for transfer. Publish its checksum alongside the application checksum through a trusted channel; self-contained file hashes detect corruption, but do not establish publisher identity by themselves.

The manual **Local release candidate** GitHub workflow runs checks and the image gate, builds/validates the ZIP, and exports the same sandbox plus checksums as an Actions artifact. It does not automatically publish, deploy, or choose a distribution license. The canonical repository's required checks, protected environments, and publisher identity must be configured by its owner.

## Install and activate

Choose a private installation home outside every project workspace. `install` creates a fresh version folder and a fresh Python environment; it downloads only the exact hash-locked packages. Do not run it as administrator.

```powershell
python scripts/release.py install .prism/dist/prism-1.0.0-rc.1.zip --home .prism/installed
docker load -i .prism/dist/prism-sandbox-1.0.0-rc.1.tar
python scripts/release.py activate 1.0.0-rc.1 --home .prism/installed
python scripts/release.py run --home .prism/installed
```

On first install, configure `.prism/installed/config.env` privately with the real NVIDIA key/model and an explicit credential-free workspace. An empty private workspace and random approval secret are generated; existing config is preserved. `STATE_DIR` is outside version folders. API pairing credentials are generated per process and never saved by the installer. Installed releases select the recorded sandbox image ID; a rebuilt mutable tag cannot silently replace that image.

Installation refuses archive traversal, duplicate entries, links, Windows device/path aliases, oversized archives, and incorrect file hashes. It refuses to overwrite an existing version. A failed dependency install leaves an unactivated folder for diagnosis. Remove only that explicitly identified failed version when retrying; never recursively clean the installation home or workspace as a troubleshooting shortcut.

After install, run the installed version's `scripts/doctor.py` with `PRISM_ENV_FILE` pointing to the installation's `config.env`, and perform a disposable-project end-to-end check. The immutable file manifest is verified again on activation and launch. Close the app with Ctrl+C before changing the active pointer; a live instance's state lock blocks activation/rollback.

## Rehearse rollback

After installing and checking a second candidate, stop the app:

```powershell
python scripts/release.py activate 1.0.0-rc.2 --home .prism/installed
python scripts/release.py rollback --home .prism/installed
python scripts/release.py run --home .prism/installed
```

Rollback verifies the previous version and atomically switches `current.json`, preserving `config.env` and access policy. Rehearse it with two actual installed candidates before publishing. It does not undo approved changes to the user's project; use project checkpoints and follow [workspace recovery](RUNBOOK.md).

## Updating locks

Use the pinned uv from `config/requirements/tools.lock`:

```powershell
uv pip compile config/requirements/runtime.in --universal --python-version 3.11 --generate-hashes -o config/requirements/runtime.lock
uv pip compile config/requirements/bootstrap.in --universal --python-version 3.11 --generate-hashes -o config/requirements/bootstrap.lock
uv pip compile config/requirements/tools.in --universal --python-version 3.11 --generate-hashes -o config/requirements/tools.lock
uv pip compile sandbox/requirements.in --universal --python-version 3.11 --generate-hashes -o sandbox/requirements.lock
```

Review lock changes with tests and advisories; then rebuild the sandbox if its inputs changed. The Dockerfile pins both official base-image digests and verifies npm's published tarball integrity before replacing the base's bundled npm. OS security packages are resolved at image build time; promote the resulting image itself rather than assuming a later rebuild is byte-identical.
