"""Explicit additional publishers; never infer trust from a catalog slug."""
from __future__ import annotations
import re

EXTRA_APPS = {
    'solidcraft': {
        'owner': 'tangency-labs',
        'name': 'SolidCraft',
        'description': 'Parametrisch 3D-ontwerp en modelleren',
    },
}


def app_owner(slug: str, default_owner: str = 'storytold') -> str:
    entry = EXTRA_APPS.get(slug)
    return entry['owner'] if entry else default_owner


def repository(db, slug: str, default_owner: str = 'storytold') -> tuple[str, str]:
    row = db.one('SELECT owner, repository FROM app_sources WHERE slug=?', (slug,))
    return (row['owner'], row['repository']) if row else (app_owner(slug, default_owner), slug)


def valid_repository(owner: str, name: str) -> bool:
    return bool(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?', owner)
                and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', name) and name not in {'.', '..'})
