# -*- coding: utf-8 -*-
"""Public announcements for Ambera Farm. No Pygame, authentication or secrets.

Drafts and a network cache are under the player's profile, NOT the installation.
The public feed can be changed independently of game EXE releases.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from urllib.request import Request, urlopen

REPO = 'AnberaForm/AmberaFarm'
FEED_PATH = 'data/announcements.json'
FEED_URL = f'https://raw.githubusercontent.com/{REPO}/main/{FEED_PATH}'
RELEASES_URL = f'https://github.com/{REPO}/releases'
LATEST_URL = RELEASES_URL + '/latest'
MAX_FEED_BYTES = 70_000
TYPES = ('news', 'update', 'event', 'maintenance')


def profile_dir() -> Path:
    from farm_core import state_path
    return state_path().parent


def cached_path() -> Path:
    return profile_dir() / 'announcements_cache.json'


def draft_path() -> Path:
    return profile_dir() / 'announcements_draft.json'


def seen_path() -> Path:
    return profile_dir() / 'announcements_seen.json'


def bundled_path() -> Path:
    return Path(__file__).resolve().parent / FEED_PATH


def validate_notice(item):
    if not isinstance(item, dict):
        raise ValueError('お知らせ形式が不正です')
    ident = item.get('id')
    if not isinstance(ident, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', ident):
        raise ValueError('お知らせIDは半角英数字と_-の64文字以内')
    for key, length in (('title', 100), ('body', 1800)):
        value = item.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > length:
            raise ValueError(f'{key} は必須（最大{length}文字）')
    if item.get('category') not in TYPES:
        raise ValueError('お知らせの種類が不正です')
    for key in ('pinned', 'published'):
        if type(item.get(key)) is not bool:
            raise ValueError(key + ' は真偽値にしてください')
    date = item.get('published_at', '')
    if not isinstance(date, str) or len(date) > 40:
        raise ValueError('掲載日時が不正です')
    url = item.get('url', '')
    if not isinstance(url, str) or len(url) > 500:
        raise ValueError('URLが不正です')
    # Only the official distribution page is linked from public announcements.
    if url and not (url == RELEASES_URL or url == LATEST_URL or
                    re.fullmatch(r'https://github\.com/AnberaForm/AmberaFarm/releases/tag/v[0-9]+\.[0-9]+\.[0-9]+', url)):
        raise ValueError('リンクは公式GitHub ReleasesのURLのみ利用できます')
    return {
        'id': ident, 'title': item['title'].strip(), 'body': item['body'].strip(),
        'category': item['category'], 'pinned': item['pinned'],
        'published': item['published'], 'published_at': date,
        'url': url,
    }


def validate_feed(obj):
    if not isinstance(obj, dict) or obj.get('schema') != 1 or not isinstance(obj.get('notices'), list):
        raise ValueError('お知らせファイルの形式が不正です')
    if len(obj['notices']) > 40:
        raise ValueError('お知らせは最大40件まで')
    found = set()
    records = []
    for item in obj['notices']:
        clean = validate_notice(item)
        if clean['id'] in found:
            raise ValueError('お知らせIDが重複: ' + clean['id'])
        found.add(clean['id'])
        records.append(clean)
    return {'schema': 1, 'notices': records}


def public_view(feed):
    """Game only renders published notices, ordered pinned/newest first."""
    records = (n for n in validate_feed(feed)['notices'] if n['published'])
    return sorted(records, key=lambda n: (n['pinned'], n['published_at'], n['id']), reverse=True)


def read_feed(path: Path):
    return validate_feed(json.loads(Path(path).read_text(encoding='utf-8-sig')))


def encode_feed(feed):
    return (json.dumps(validate_feed(feed), ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def atomic_write(path: Path, payload: bytes):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.ambera_notice_', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(payload)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_feed(path: Path, feed):
    atomic_write(path, encode_feed(feed))


def load_draft():
    p = draft_path()
    if p.exists():
        return read_feed(p)
    p = cached_path()
    if p.exists():
        try:
            return read_feed(p)
        except (OSError, ValueError, UnicodeError):
            pass
    return read_feed(bundled_path())


def load_offline():
    for p in (cached_path(), bundled_path()):
        try:
            return read_feed(p)
        except (OSError, ValueError, UnicodeError):
            pass
    return {'schema': 1, 'notices': []}


def fetch_public(timeout=6):
    """Fetch public read-only data. Never include player credentials or save data."""
    req = Request(FEED_URL, headers={'User-Agent': 'AmberaFarm-News/0.7', 'Cache-Control': 'no-cache'})
    with urlopen(req, timeout=timeout) as resp:
        if resp.geturl().split('?')[0] != FEED_URL:
            raise ValueError('お知らせの接続先が変更されました')
        raw = resp.read(MAX_FEED_BYTES + 1)
    if len(raw) > MAX_FEED_BYTES:
        raise ValueError('お知らせが容量上限を超えています')
    feed = validate_feed(json.loads(raw.decode('utf-8-sig')))
    save_feed(cached_path(), feed)
    return feed


def load_seen():
    try:
        obj = json.loads(seen_path().read_text(encoding='utf-8-sig'))
        if not isinstance(obj, list) or len(obj) > 2000:
            return set()
        return {x for x in obj if isinstance(x, str) and len(x) <= 64}
    except (OSError, ValueError, UnicodeError):
        return set()


def mark_seen(notice_id, current=None):
    if current is None:
        current = load_seen()
    if not isinstance(notice_id, str) or len(notice_id) > 64:
        return current
    updated = set(current)
    updated.add(notice_id)
    atomic_write(seen_path(), (json.dumps(sorted(updated)[-1000:]) + '\n').encode('utf-8'))
    return updated


def unread_count(feed, seen):
    return sum(n['id'] not in seen for n in public_view(feed))
