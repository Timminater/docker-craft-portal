"""Narrow hosting adaptations for explicitly supported third-party apps."""
import re

_SCRIPT = re.compile(r'<script\b[^>]*>(.*?)</script\s*>', re.I | re.S)
_REGISTRATION = 'if("serviceWorker"innavigator){addEventListener("load",()=>navigator.serviceWorker.register("sw.js").catch(()=>{}));}'


def solidcraft_index(source: str) -> str:
    """Remove only the known standalone offline registration; preserve other code.

    Unknown registration code fails closed before activation rather than disabling
    ordinary workers or accidentally removing application startup code.
    """
    def adapt(match):
        body = match.group(1)
        if 'serviceWorker' not in body or '.register' not in body:
            return match.group(0)
        body = re.sub(r'^\s*//[^\r\n]*', '', body, flags=re.M)
        compact = re.sub(r'\s+', '', body).replace("'", '"')
        if compact != _REGISTRATION:
            raise ValueError('Unsupported SolidCraft offline registration; preserving installed version')
        return '<!-- Offline application caching disabled for authenticated portal hosting. -->'
    result = _SCRIPT.sub(adapt, source)
    if not re.search(r'rel=[\"\']icon[\"\']', result, re.I):
        result = result.replace('</head>', '<link rel="icon" href="data:,"></head>', 1)
    return result
