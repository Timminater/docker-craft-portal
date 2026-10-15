"""Offline, checksum-verified snapshots. Stop the portal before backup or restore."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile


def checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def regular_files(root: Path) -> list[Path]:
    files = []
    for path in root.rglob('*'):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError('Snapshots must not contain links or special files')
        if path.is_file():
            files.append(path)
    return files


def check_database(path: Path):
    with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro&immutable=1', uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('SQLite integrity check failed')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('SQLite foreign key check failed')


def backup(data_dir: Path, output: Path):
    data_dir, output = data_dir.resolve(), output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Backup destination already exists')
    if output.resolve().is_relative_to(data_dir):
        raise ValueError('Place backups outside the live data directory')
    database = data_dir / 'database' / 'portal.sqlite'
    if not database.is_file() or database.is_symlink():
        raise ValueError('Portal database not found or unsafe')
    # Validate paths before following any source trees.
    regular_files(data_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.craft-backup-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'snapshot'
        (stage / 'database').mkdir(parents=True, mode=0o700)
        snapshot_db = stage / 'database' / 'portal.sqlite'
        with closing(sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(snapshot_db)) as target:
                source.backup(target)
                target.execute('PRAGMA journal_mode=DELETE')
        check_database(snapshot_db)
        apps = data_dir / 'apps'
        if apps.exists():
            shutil.copytree(apps, stage / 'apps')
        files = regular_files(stage)
        manifest = {'format': 1, 'files': {str(p.relative_to(stage)): checksum(p) for p in files}}
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        for path in stage.rglob('*'):
            path.chmod(0o700 if path.is_dir() else 0o600)
        stage.chmod(0o700)
        os.rename(stage, output)


def restore(snapshot: Path, data_dir: Path):
    if snapshot.is_symlink():
        raise ValueError('Snapshot root must not be a link')
    snapshot, data_dir = snapshot.resolve(), data_dir.absolute()
    if data_dir.exists() or data_dir.is_symlink():
        raise ValueError('Restore requires a new, absent data directory')
    files = regular_files(snapshot)
    manifest = json.loads((snapshot / 'manifest.json').read_text())
    if manifest.get('format') != 1 or not isinstance(manifest.get('files'), dict):
        raise ValueError('Unsupported snapshot manifest')
    actual = {str(p.relative_to(snapshot)): checksum(p) for p in files if p.name != 'manifest.json' or p.parent != snapshot}
    if actual != manifest['files'] or 'database/portal.sqlite' not in actual:
        raise ValueError('Snapshot file list or checksum mismatch')
    if any(not (p == 'database/portal.sqlite' or p.startswith('apps/')) for p in actual):
        raise ValueError('Unexpected snapshot contents')
    check_database(snapshot / 'database' / 'portal.sqlite')
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.craft-restore-', dir=data_dir.parent) as temporary:
        stage = Path(temporary) / 'data'
        stage.mkdir(mode=0o700)
        for name in actual:
            source = snapshot / name
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(source, target)
            target.chmod(0o600)
        # Restored credentials must not resurrect browser sessions or launch tickets.
        with closing(sqlite3.connect(stage / 'database' / 'portal.sqlite')) as db:
            with db:
                db.execute('DELETE FROM launch_tickets')
                db.execute('DELETE FROM sessions')
                # Older snapshots predate MFA enrollment; retain activated
                # factors/recovery hashes, discard unfinished secret enrollment.
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_mfa_pending'").fetchone():
                    db.execute('DELETE FROM account_mfa_pending')
        (stage / 'staging').mkdir(mode=0o700)
        os.rename(stage, data_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    save = commands.add_parser('backup', help='Stop the portal first, including its updater')
    save.add_argument('--data-dir', required=True, type=Path)
    save.add_argument('--output', required=True, type=Path)
    load = commands.add_parser('restore', help='Restore into a new data directory; never overwrite live data')
    load.add_argument('--snapshot', required=True, type=Path)
    load.add_argument('--data-dir', required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'backup':
            backup(args.data_dir, args.output)
        else:
            restore(args.snapshot, args.data_dir)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f'{exc}\n')
    print('Snapshot ' + ('created' if args.command == 'backup' else 'restored; all sessions revoked'))


if __name__ == '__main__':
    main()
