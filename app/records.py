"""公开目录与日历巡查收据。

两张表职责分离：
- catalog / calendar_visits 为追加式收据，记录每一次浏览器观察，永不改写；
- calendar_facts 为当前事实表，按业务键只保留当前版本，写入必须通过
  domain.decide_fact_update 状态机：修改生成新版本并留痕，取消不接受任何
  在档观察“复活”，幂等重跑不产生新版本。
"""
import json
import sqlite3
import time
from pathlib import Path
from .domain import decide_fact_update


def save_catalog(path, items):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS catalog (id TEXT PRIMARY KEY, source TEXT NOT NULL, payload TEXT NOT NULL)')
        for item in items:
            db.execute('INSERT OR REPLACE INTO catalog VALUES (?, ?, ?)', (item['id'], item['source'], json.dumps(item, ensure_ascii=False)))
    return len(items)


def save_detail_entries(path, entries):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS detail_entries (visit_id INTEGER PRIMARY KEY, item_id TEXT NOT NULL, business_key TEXT NOT NULL, source TEXT NOT NULL, payload TEXT NOT NULL)')
        for entry in entries:
            if entry['catalog_fact']['identity'] != entry['id']:
                raise ValueError('catalog and detail identity mismatch')
            db.execute('INSERT INTO detail_entries (item_id, business_key, source, payload) VALUES (?, ?, ?, ?)',
                       (entry['id'], entry['detail_fact']['business_key'], entry['source'], json.dumps(entry, ensure_ascii=False)))
    return len(entries)


def read_detail_entries(path):
    with sqlite3.connect(path) as db:
        rows = db.execute('SELECT payload FROM detail_entries ORDER BY visit_id').fetchall()
    return [json.loads(row[0]) for row in rows]


def _ensure_calendar_tables(db):
    db.execute('CREATE TABLE IF NOT EXISTS calendar_visits ('
               'visit_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, business_key TEXT NOT NULL,'
               ' item_id TEXT NOT NULL, month TEXT NOT NULL, day TEXT NOT NULL,'
               ' source TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL,'
               ' observed_at REAL NOT NULL, payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS calendar_facts ('
               'business_key TEXT PRIMARY KEY, item_id TEXT NOT NULL,'
               ' month TEXT NOT NULL, day TEXT NOT NULL, state TEXT NOT NULL,'
               ' revision INTEGER NOT NULL DEFAULT 1, run_id TEXT,'
               ' observed_at REAL NOT NULL, source TEXT NOT NULL, payload TEXT NOT NULL)')


def save_calendar_observations(path, run, *, observed_at=None):
    """把一次巡查的观察落库。

    run 为 read_calendar 的返回（含 observations 与 gaps）。每条观察都写入
    calendar_visits；是否更新 calendar_facts 由状态机决定。返回写入统计，
    缺口数保留在 run['gaps'] 中，供审阅层判定月份是否只够格做草稿。
    """
    observed_at = time.time() if observed_at is None else observed_at
    run_id = run.get('run_id') or f'run-{int(observed_at * 1000)}'
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stats = {'inserted': 0, 'revised': 0, 'kept': 0, 'rejected': 0, 'visits': 0}
    with sqlite3.connect(path) as db:
        _ensure_calendar_tables(db)
        for observation in run['observations']:
            incoming = dict(observation)
            if incoming.get('run_id') is None:
                incoming['run_id'] = run_id
            if incoming.get('observed_at') is None:
                incoming['observed_at'] = observed_at
            key = incoming['business_key']
            row = db.execute(
                'SELECT payload, revision FROM calendar_facts WHERE business_key = ?',
                (key,)).fetchone()
            if row is None:
                stored, revision = None, 0
            else:
                stored, revision = json.loads(row[0]), row[1]
            action, reason = decide_fact_update(stored, incoming)
            db.execute('INSERT INTO calendar_visits '
                       '(run_id, business_key, item_id, month, day, source, action, reason, observed_at, payload) '
                       'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                       (run_id, key, incoming['event'], incoming['month'], incoming['day'],
                        incoming['source'], action, reason, incoming['observed_at'],
                        json.dumps(incoming, ensure_ascii=False)))
            stats['visits'] += 1
            if action == 'insert':
                db.execute('INSERT INTO calendar_facts '
                           '(business_key, item_id, month, day, state, revision, run_id, observed_at, source, payload) '
                           'VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)',
                           (key, incoming['event'], incoming['month'], incoming['day'],
                            incoming['state'], run_id, incoming['observed_at'],
                            incoming['source'], json.dumps(incoming, ensure_ascii=False)))
                stats['inserted'] += 1
            elif action == 'revise':
                db.execute('UPDATE calendar_facts SET state = ?, revision = ?, run_id = ?,'
                           ' observed_at = ?, source = ?, payload = ? WHERE business_key = ?',
                           (incoming['state'], revision + 1, run_id, incoming['observed_at'],
                            incoming['source'], json.dumps(incoming, ensure_ascii=False), key))
                stats['revised'] += 1
            elif action == 'reject':
                stats['rejected'] += 1
            else:
                stats['kept'] += 1
    return stats


def read_calendar_facts(path):
    with sqlite3.connect(path) as db:
        _ensure_calendar_tables(db)
        rows = db.execute('SELECT payload FROM calendar_facts ORDER BY observed_at, business_key').fetchall()
    return [json.loads(row[0]) for row in rows]


def read_calendar_visits(path):
    with sqlite3.connect(path) as db:
        _ensure_calendar_tables(db)
        rows = db.execute('SELECT payload FROM calendar_visits ORDER BY visit_id').fetchall()
    return [json.loads(row[0]) for row in rows]
