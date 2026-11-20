#!/usr/bin/env python3
"""Read-only rolling-volume and capacity monitor for gnosis.bot.

No provider calls, no account data, and no automatic resource scaling.
Uses saved completed consultations across apps, never raw shots.
State is stored separately from SQLite. Cron/systemd may run this hourly.
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import smtplib
import ssl
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gnosis_platform.config import get_settings


def evaluate(db, *, now=None, disk_path=None, warning_count=1000, urgent_count=2500):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now must be timezone-aware')
    now = now.astimezone(timezone.utc)
    start = (now - timedelta(hours=24)).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    end = now.isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    # One saved reading per completed consultation across applications.
    n = int(db.execute("SELECT COUNT(*) FROM consultations c JOIN reading_results r ON r.consultation_id=c.consultation_id WHERE c.status='completed' AND c.finished_at>=? AND c.finished_at<?", (start, end)).fetchone()[0])
    if n > urgent_count:
        volume_level = 'critical'
    elif n > warning_count:
        volume_level = 'warning'
    else:
        volume_level = 'normal'
    target = Path(disk_path).expanduser().resolve() if disk_path else None
    disk = None
    if target is not None:
        if not target.exists():
            raise FileNotFoundError(f'Monitored disk path not found: {target}')
        usage = shutil.disk_usage(target)
        pct = 100 * usage.used / usage.total if usage.total else 0
        level = 'critical' if pct >= 85 else 'warning' if pct >= 70 else 'normal'
        disk = {'path': str(target), 'used_percent': round(pct, 2), 'free_bytes': usage.free, 'level': level}
    return {'observed_at_utc': end, 'window_start_utc': start, 'window_hours': 24,
            'completed_readings_24h': n, 'volume_level': volume_level,
            'warning_above': warning_count, 'critical_above': urgent_count, 'disk': disk}


def alert_changes(previous, current):
    # Notify on transition into a threshold, escalation, or recovery.
    state = {'volume': current['volume_level'], 'disk': current['disk']['level'] if current['disk'] else 'unmonitored'}
    prior = previous.get('levels', {})
    events = []
    if state['volume'] != prior.get('volume', 'normal'):
        events.append(f"readings/24h {prior.get('volume', 'normal')} -> {state['volume']} ({current['completed_readings_24h']} completed)")
    if state['disk'] != prior.get('disk', 'unmonitored'):
        events.append(f"disk {prior.get('disk', 'unmonitored')} -> {state['disk']}")
    return state, events


def send_email(subject, body):
    """Email only if explicitly configured; otherwise rely on stdout/system journal."""
    host = os.getenv('GNOSIS_ALERT_SMTP_HOST')
    sender = os.getenv('GNOSIS_ALERT_FROM')
    recipient = os.getenv('GNOSIS_ALERT_TO')
    if not (host and sender and recipient):
        return False
    port = int(os.getenv('GNOSIS_ALERT_SMTP_PORT', '465'))
    user = os.getenv('GNOSIS_ALERT_SMTP_USER')
    password = os.getenv('GNOSIS_ALERT_SMTP_PASSWORD')
    msg = EmailMessage()
    msg['Subject'], msg['From'], msg['To'] = subject, sender, recipient
    msg.set_content(body)
    with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=20) as server:
        if user:
            if not password:
                raise ValueError('SMTP password is missing')
            server.login(user, password)
        server.send_message(msg)
    return True


def save_state(path, payload):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, tmp = tempfile.mkstemp(prefix='.gnosis-monitor-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf8') as f:
            json.dump(payload, f, separators=(',', ':'), sort_keys=True)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main():
    ap = argparse.ArgumentParser(description='Gnosis rolling 24-hour reading-volume and disk alert')
    ap.add_argument('--db', help='Existing production SQLite path (default GNOSIS_DB_PATH / app config)')
    ap.add_argument('--disk-path', help='Production data filesystem path to monitor')
    ap.add_argument('--state', default=str(get_settings().data_dir/'volume-alert-state.json'))
    ap.add_argument('--warning', type=int, default=1000)
    ap.add_argument('--critical', type=int, default=2500)
    ap.add_argument('--dry-run', action='store_true', help='No state file update or email')
    args = ap.parse_args()
    if args.warning < 0 or args.critical <= args.warning:
        ap.error('Thresholds must satisfy 0 <= warning < critical')
    from gnosis_platform.config import get_settings
    from gnosis_platform.db import connect
    db_path = Path(args.db).expanduser().resolve() if args.db else get_settings().db_path
    if not db_path.is_file():
        ap.error(f'Database does not exist: {db_path} (refusing to create one)')
    import sqlite3
    uri = f'{db_path.as_uri()}?mode=ro'
    with sqlite3.connect(uri, uri=True, timeout=15) as db:
        current = evaluate(db, disk_path=args.disk_path or db_path.parent, warning_count=args.warning, urgent_count=args.critical)
    state_path = Path(args.state).expanduser()
    old = json.loads(state_path.read_text()) if state_path.is_file() else {}
    levels, events = alert_changes(old, current)
    print(json.dumps({'metrics': current, 'events': events, 'dry_run': args.dry_run}, indent=2))
    if args.dry_run:
        return
    if events:
        body = '\n'.join(events) + '\n\n' + json.dumps(current, indent=2)
        # On failure, do not update the state, so the next run retries sending.
        if not send_email('[gnosis.bot] Operating thresholds changed', body):
            print('ALERT (stdout only; configure GNOSIS_ALERT_SMTP_* for email): '+', '.join(events), file=sys.stderr)
    save_state(state_path, {'levels': levels, 'updated_at_utc': current['observed_at_utc']})


if __name__ == '__main__':
    main()
