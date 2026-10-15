import pytest
from pathlib import Path
from portal.config import Config
from portal.server import create_app


@pytest.fixture
def factory(tmp_path):
    def build(*, multi_user=False):
        return create_app(Config(data_dir=tmp_path,public_url="http://localhost:8080" if not multi_user else "https://craft.example.test",apps_domain="apps.example.test" if multi_user else "",auto_start_updates=False),start_updater=False)
    return build
