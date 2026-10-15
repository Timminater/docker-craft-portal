"""Exercise the background schedule without waiting six hours in real time."""
from types import SimpleNamespace

from portal.config import Config
from portal.database import Database
from portal.updater import Updater


def test_background_starts_immediately_then_checks_after_six_hours(tmp_path, monkeypatch):
    db = Database(tmp_path / 'database/portal.sqlite')
    updater = Updater(Config(data_dir=tmp_path, public_url='http://localhost:8080', apps_domain=''), db)
    clock = [1000.0]
    calls = []
    monkeypatch.setattr('portal.updater.time', SimpleNamespace(time=lambda: clock[0]))

    def check():
        calls.append(clock[0])
        updater.next_check = clock[0] + int(db.setting('update_interval_hours')) * 3600
        if len(calls) == 2:
            updater.stop_event.set()
        return True

    def wait(seconds):
        clock[0] += seconds
        return updater.stop_event.is_set()

    monkeypatch.setattr(updater, 'check', check)
    monkeypatch.setattr(updater.stop_event, 'wait', wait)
    updater.start()
    updater.thread.join(timeout=5)
    assert not updater.thread.is_alive()
    assert calls == [1000.0, 1000.0 + 6 * 3600]
    updater.stop()
    db.close()
