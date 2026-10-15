#!/usr/bin/env python3
"""Opt-in live release check. Run with dev dependencies; writes a JSON report.

python scripts/verify_official_releases.py --run-live --report /tmp/releases.json
Downloads every catalog app into temporary storage, verifies publisher/digest,
then checks authenticated versioned asset responses. This does not execute WASM
or replace Chromium/Firefox compatibility tests. Never use production data.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from portal.config import Config
from portal.server import create_app
from portal.updater import discover_slugs, parse_release, verify_official_app_page


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live',action='store_true',help='Consent to downloading every official release (potentially several GB)')
    parser.add_argument('--report',type=Path,default=Path('/tmp/craft-official-releases.json'))
    args=parser.parse_args()
    if not args.run_live: parser.error('--run-live is required; this performs real network downloads')
    # Startup codes and HTTP request URLs must not enter this report or logs.
    previous_logging_disable=logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    report={'scope':'official releases, integrity, authenticated HTTP assets; no browser execution','apps':[]}
    with tempfile.TemporaryDirectory(prefix='craft-live-') as storage:
        cfg=Config(data_dir=Path(storage),public_url='https://portal.example.test',apps_domain='',single_app_url='https://apps.example.test',github_token=os.getenv('GITHUB_TOKEN',''),auto_start_updates=False)
        app=create_app(cfg,start_updater=False)
        updater=app.state.updater
        try:
            with TestClient(app,base_url=cfg.public_url) as portal:
                password=secrets.token_urlsafe(24)
                response=portal.post('/api/setup',headers={'X-Craft-Client':'portal-v1'},json={'code':app.state.auth.setup_code,'username':'verification','password':password})
                response.raise_for_status()
                csrf=portal.get('/api/bootstrap').json()['csrf']
                slugs=discover_slugs(updater.request(cfg.catalog_url).decode(),cfg.catalog_url)
                report['catalog_apps']=slugs
                for slug in slugs:
                    entry={'slug':slug,'ok':False};report['apps'].append(entry)
                    try:
                        verify_official_app_page(updater.request(f'{cfg.catalog_url}/{slug}').decode(),slug,cfg.catalog_url,cfg.trusted_owner)
                        release=parse_release(slug,json.loads(updater.request(f'https://api.github.com/repos/{cfg.trusted_owner}/{slug}/releases/latest')),cfg.trusted_owner)
                        entry.update(version=release['version'],digest=release['asset']['digest'],archive_bytes=release['asset']['size'])
                        app.state.db.run('INSERT OR IGNORE INTO apps(slug,name,description) VALUES(?,?,?)',(slug,slug,'Live verification'))
                        updater.install(slug,release)
                        launch=portal.post(f'/api/apps/{slug}/launch',headers={'X-Craft-Client':'portal-v1','X-Craft-CSRF':csrf})
                        launch.raise_for_status()
                        ticket=parse_qs(urlparse(launch.json()['url']).fragment)['ticket'][0]
                        # Avoid nested lifespan contexts, which would close the shared DB.
                        with closing(TestClient(app,base_url=cfg.single_app_url)) as assets:
                            redeem=assets.post('/_redeem',headers={'X-Craft-Client':'app-bridge-v1'},json={'ticket':ticket,'slug':slug})
                            redeem.raise_for_status()
                            base=cfg.data_dir/'apps'/slug/'versions'/release['version']
                            candidates=[base/'index.html']
                            for suffix in ('.js','.wasm'):
                                candidates.extend(list(base.rglob('*'+suffix))[:1])
                            checks=[]
                            for file in candidates:
                                response=assets.get(f'/a/{slug}/v/{release["version"]}/{file.relative_to(base).as_posix()}')
                                response.raise_for_status()
                                checks.append({'asset':file.relative_to(base).as_posix(),'content_type':response.headers.get('content-type'),'coop':response.headers.get('cross-origin-opener-policy'),'coep':response.headers.get('cross-origin-embedder-policy'),'cache_control':response.headers.get('cache-control')})
                                if file.suffix=='.wasm' and response.headers.get('content-type')!='application/wasm':raise RuntimeError('WASM MIME mismatch')
                            entry['headers']=checks
                            entry['service_workers']=[p.relative_to(base).as_posix() for p in base.rglob('*.js') if 'service-worker' in p.name.lower() or p.name=='sw.js']
                        entry['ok']=True
                    except Exception as exc:
                        # Exception text may contain signed CDN URLs; record class only.
                        entry['error_type']=type(exc).__name__
        except Exception as exc:
            report['error_type']=type(exc).__name__
    logging.disable(previous_logging_disable)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(f'Report: {args.report}; verified {sum(a["ok"] for a in report["apps"])} apps')
    return 0 if report['apps'] and all(a['ok'] for a in report['apps']) and 'error_type' not in report else 1


if __name__=='__main__':
    raise SystemExit(main())
