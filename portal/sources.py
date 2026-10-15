"""Explicit additional publishers; never infer trust from a catalog slug."""
from __future__ import annotations

EXTRA_APPS = {
    'solidcraft': {
        'owner': 'bherbruck',
        'name': 'SolidCraft',
        'description': 'Parametrisch 3D-ontwerp en modelleren',
    },
}


def app_owner(slug: str, default_owner: str = 'storytold') -> str:
    entry = EXTRA_APPS.get(slug)
    return entry['owner'] if entry else default_owner
