from io import BytesIO
from urllib.request import Request

import pytest
from fastapi.testclient import TestClient

from portal.artwork import Artwork, ArtworkRedirect, FALLBACK, MAX_BYTES, trusted_url
from tests.test_security import headers, setup

# Minimal RIFF container with a WebP chunk: validation inspects the container.
WEBP = b'RIFF' + (16).to_bytes(4, 'little') + b'WEBPVP8 ' + (4).to_bytes(4, 'little') + b'data'


class Response(BytesIO):
    def __init__(self, body=WEBP, length=None, url='https://getartcraft.com/images/apps/photocraft/icon.webp'):
        super().__init__(body)
        self.headers = {} if length is None else {'Content-Length': length}
        self.url = url

    def geturl(self):
        return self.url


class Opener:
    def __init__(self, response=None, failure=False):
        self.response = response
        self.failure = failure
        self.calls = []

    def open(self, request, timeout):
        self.calls.append(request)
        assert timeout == 5
        assert request.get_header('Authorization') is None
        if self.failure:
            raise OSError('offline')
        return self.response


def test_cache_verified_bytes_and_offline_reuse(tmp_path):
    art = Artwork(tmp_path, tmp_path / 'static', True)
    art.opener = Opener(Response())
    assert art.get('photocraft', 'icon') == (WEBP, 'image/webp')
    assert len(art.opener.calls) == 1
    assert art.opener.calls[0].full_url == 'https://getartcraft.com/images/apps/photocraft/icon.webp'
    offline = Artwork(tmp_path, tmp_path / 'static', False)
    offline.opener = Opener(failure=True)
    assert offline.get('photocraft', 'icon') == (WEBP, 'image/webp')
    assert not offline.opener.calls
    assert not list((tmp_path / 'artwork/photocraft').glob('.artwork-*'))


@pytest.mark.parametrize('response', [
    lambda: Response(length=str(MAX_BYTES + 1)),
    lambda: Response(length='garbage'),
    lambda: Response(body=b'x' * (MAX_BYTES + 1)),
    lambda: Response(body=b'not a webp'),
    lambda: Response(url='https://attacker.example/image.webp'),
])
def test_failed_fetch_falls_back_and_is_negatively_cached(tmp_path, response):
    art = Artwork(tmp_path, tmp_path / 'static', True)
    art.opener = Opener(response())
    assert art.get('photocraft', 'hero') == (FALLBACK, 'image/svg+xml')
    assert art.get('photocraft', 'hero') == (FALLBACK, 'image/svg+xml')
    assert len(art.opener.calls) == 1
    assert not (tmp_path / 'artwork/photocraft/hero.webp').exists()


def test_offline_uses_bundled_icon_without_network(tmp_path):
    icon = tmp_path / 'static/artcraft/photocraft/icon.png'
    icon.parent.mkdir(parents=True)
    png = b'\x89PNG\r\n\x1a\n' + b'bundled'
    icon.write_bytes(png)
    art = Artwork(tmp_path, tmp_path / 'static', False)
    art.opener = Opener(failure=True)
    assert art.get('photocraft', 'icon') == (png, 'image/png')
    assert art.get('photocraft', 'hero') == (FALLBACK, 'image/svg+xml')
    assert not art.opener.calls


@pytest.mark.parametrize('target', ['http://getartcraft.com/x', 'https://evil.test/x',
                                  'https://getartcraft.com.evil.test/x',
                                  'https://user:pass@getartcraft.com/x', 'https://getartcraft.com:8443/x'])
def test_redirects_restricted_to_official_https(target):
    assert not trusted_url(target)
    with pytest.raises(ValueError):
        ArtworkRedirect().redirect_request(Request('https://getartcraft.com/x'), None, 302, 'Found', {}, target)


def test_allowed_redirect_has_small_loop_limit():
    redirect = ArtworkRedirect()
    result = redirect.redirect_request(Request('https://getartcraft.com/x'), None, 302, 'Found', {},
                                       'https://www.getartcraft.com/x')
    assert result.full_url == 'https://www.getartcraft.com/x'
    assert redirect.max_redirections == 3 and redirect.max_repeats == 1


def test_artwork_route_requires_portal_auth_and_known_app(factory):
    app = factory()
    with TestClient(app, base_url='http://localhost:8080') as portal:
        art = app.state.artwork
        art.opener = Opener(failure=True)
        path = '/static/artcraft/photocraft/icon.webp'
        assert portal.get(path).status_code == 401
        assert setup(portal, app).status_code == 200
        assert portal.get(path).status_code == 404
        app.state.db.run("INSERT INTO apps(slug,name) VALUES('photocraft','PhotoCraft')")
        assert portal.get('/static/artcraft/photocraft/unknown.webp').status_code == 404
        response = portal.get(path)
        assert response.status_code == 200
        assert response.headers['content-type'] in {'image/svg+xml', 'image/png'}
        assert response.headers['cache-control'] == 'private, no-store'
        app_client = TestClient(app, base_url='http://127.0.0.1:8080')
        assert app_client.get(path).status_code == 421
        assert not art.opener.calls
        assert portal.post('/api/logout', headers=headers(portal.get('/api/bootstrap').json()['csrf'])).status_code == 200
        assert portal.get(path).status_code == 401


@pytest.mark.parametrize('slug,kind', [('../secrets', 'hero'), ('photocraft', '../x'), ('', 'icon')])
def test_reject_unsafe_identifiers(tmp_path, slug, kind):
    with pytest.raises(ValueError):
        Artwork(tmp_path, tmp_path, False).get(slug, kind)


def test_artwork_never_served_on_valid_app_host(factory):
    app = factory(multi_user=True)
    with TestClient(app, base_url='https://craft.example.test') as portal:
        assert setup(portal, app).status_code == 200
        user = app.state.db.one("SELECT public_id FROM users WHERE username='admin'")
        client = TestClient(app, base_url=f"https://photocraft--{user['public_id']}.apps.example.test")
        assert client.get('/static/artcraft/photocraft/icon.webp').status_code == 404
