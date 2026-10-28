"""Narrow hosting adaptations for explicitly supported third-party apps."""
import re

_SCRIPT = re.compile(r'<script\b[^>]*>(.*?)</script\s*>', re.I | re.S)
_SAFE_REGISTRATION = re.compile(r'''if\s*\(\s*["']serviceWorker["']\s+in\s+navigator\s*\)\s*\{\s*addEventListener\s*\(\s*["']load["']\s*,\s*\(\s*\)\s*=>\s*navigator\.serviceWorker\.register\s*\(\s*["']sw\.js["']\s*\)\.catch\s*\(\s*\(\s*\)\s*=>\s*\{\s*\}\s*\)\s*\)\s*;?\s*\}''')


def solidcraft_index(source: str) -> str:
    """Remove only the known standalone offline registration; preserve other code.

    Unknown registration code fails closed before activation rather than disabling
    ordinary workers or accidentally removing application startup code.
    """
    def adapt(match):
        body = match.group(1)
        compact_source = re.sub(r'\s+', '', body)
        if 'serviceWorker' not in compact_source or '.register' not in compact_source:
            return match.group(0)
        cleaned = _SAFE_REGISTRATION.sub('', body)
        compact = re.sub(r'\s+', '', cleaned)
        if cleaned == body or ('serviceWorker' in compact and '.register' in compact):
            raise ValueError('Unsupported SolidCraft offline registration; preserving installed version')
        return match.group(0).replace(body, cleaned)
    result = _SCRIPT.sub(adapt, source)
    if not re.search(r'rel=[\"\']icon[\"\']', result, re.I):
        result = result.replace('</head>', '<link rel="icon" href="data:,"></head>', 1)
    return result
