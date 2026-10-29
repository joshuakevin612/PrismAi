"""Apply hash-verified, dependency-free patch releases to npm's bundled copies.

npm 12.2.1 still bundles undici 6.29.0 and ip-address 10.7.2. Keep their
compatible patched versions explicit until the upstream npm bundle catches up.
"""
import base64
import hashlib
import io
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import urllib.request

MODULES = Path('/usr/local/lib/node_modules/npm/node_modules')
PATCHES = [
    ('undici','6.29.1','EvRlUt/QqAEvXdQeRMYUfwOQsfzpDztykrG2owGEE/rBOBoYv9uF39ZzsNDh4lTFHhTr2XOZjKkYgueD12ZmGA=='),
    ('ip-address','10.7.4','DWBMKyeM25D70nrIiTkgQth59/G+naKOTep6huF9j+GmeK3DMD60Zvxg5d5qQnz+38AHgou6ean2LECX+lrKDg=='),
]


def main():
    for name,version,integrity in PATCHES:
        data = urllib.request.urlopen(f'https://registry.npmjs.org/{name}/-/{name}-{version}.tgz',timeout=30).read()
        if base64.b64encode(hashlib.sha512(data).digest()).decode() != integrity:
            raise ValueError('npm patch integrity mismatch')
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
            members = archive.getmembers()
            if sum(m.size for m in members)>30_000_000:
                raise ValueError('Unexpected patch size')
            for member in members:
                path = PurePosixPath(member.name)
                if path.is_absolute() or not path.parts or path.parts[0]!='package' or '..' in path.parts or not (member.isfile() or member.isdir()):
                    raise ValueError('Unexpected npm patch path')
            target = MODULES/name
            if target.parent != MODULES or target.is_symlink():
                raise ValueError('Unsafe npm module target')
            if target.exists():
                shutil.rmtree(target)
            for member in members:
                if member.isfile():
                    path = target.joinpath(*PurePosixPath(member.name).parts[1:])
                    path.parent.mkdir(parents=True,exist_ok=True)
                    with archive.extractfile(member) as stream:
                        path.write_bytes(stream.read())
        print(f'Installed verified npm patch: {name} {version}')


if __name__ == '__main__':
    main()
