import hashlib
import io
from types import SimpleNamespace
import zipfile

import pytest

from portal.updater import InstallError


def bundle():
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('index.html', '<html>last good app</html>')
        archive.writestr('app.js', 'console.log("loaded")')
        archive.writestr('app.wasm', b'\0asm\x01\0\0\0')
    return data.getvalue()


@pytest.mark.parametrize('failure', ['digest', 'truncated', 'oversized'])
def test_verified_download_failure_preserves_active_version(factory, failure):
    app = factory()
    updater, db = app.state.updater, app.state.db
    data = bundle()
    updater.opener = SimpleNamespace(open=lambda *a, **kw: io.BytesIO(data))
    db.run("INSERT INTO apps(slug,name) VALUES('photocraft','PhotoCraft')")

    def release(version):
        return {'version': version, 'asset': {
            'browser_download_url': f'https://github.com/storytold/photocraft/releases/download/{version}/photocraft-web-{version[1:]}.zip',
            'size': len(data), 'digest': 'sha256:' + hashlib.sha256(data).hexdigest()}}

    updater.install('photocraft', release('v1.0.0'))
    next_release = release('v1.1.0')
    if failure == 'digest':
        next_release['asset']['digest'] = 'sha256:' + '0' * 64
    elif failure == 'truncated':
        updater.opener = SimpleNamespace(open=lambda *a, **kw: io.BytesIO(data[:-1]))
    else:
        updater.opener = SimpleNamespace(open=lambda *a, **kw: io.BytesIO(data + b'extra'))
    with pytest.raises(InstallError):
        updater.install('photocraft', next_release)
    assert db.one("SELECT active_version FROM apps WHERE slug='photocraft'")['active_version'] == 'v1.0.0'
    assert (app.state.cfg.data_dir / 'apps/photocraft/versions/v1.0.0/index.html').read_text() == '<html>last good app</html>'
    assert not (app.state.cfg.data_dir / 'apps/photocraft/versions/v1.1.0').exists()
    assert not list((app.state.cfg.data_dir / 'staging').iterdir())
