import pytest

from portal.config import Config


@pytest.mark.parametrize('url', [
    'https://user:password@craft.example.test', 'https://craft.example.test?x=1',
    'https://craft.example.test#secret', 'https://craft.example.test?',
    'https://craft.example.test/path', 'https://craft.example.test:99999',
    'https://bad_host.example.test', 'https://craft.example.test:',
    'https://craft.example.test\\evil', 'https://craft.example.test\n',
])
def test_reject_malformed_portal_origins(tmp_path, url):
    with pytest.raises(ValueError):
        Config(data_dir=tmp_path, public_url=url, apps_domain='')


@pytest.mark.parametrize('url', [
    'https://craft.example.test:9443', 'https://user:password@apps.example.test',
    'https://apps.example.test?x=1', 'https://apps.example.test#secret',
    'http://localhost:8080',
])
def test_reject_unsafe_app_origins(tmp_path, url):
    with pytest.raises(ValueError):
        Config(data_dir=tmp_path, public_url='https://craft.example.test', apps_domain='', single_app_url=url)


@pytest.mark.parametrize('domain', ['apps.example.test:443', '*.example.test',
                                    'bad_domain.test', '-bad.example.test', 'apps.localhost',
                                    'https://apps.example.test'])
def test_reject_malformed_apps_domain(tmp_path, domain):
    with pytest.raises(ValueError):
        Config(data_dir=tmp_path, public_url='https://craft.example.test', apps_domain=domain)


def test_local_default_has_separate_cookie_host(monkeypatch, tmp_path):
    monkeypatch.setenv('CRAFT_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('CRAFT_PUBLIC_URL', 'http://localhost:8080')
    monkeypatch.delenv('CRAFT_APPS_DOMAIN', raising=False)
    monkeypatch.delenv('CRAFT_SINGLE_APP_URL', raising=False)
    cfg = Config.from_env()
    assert cfg.single_app_url == 'http://127.0.0.1:8080'
