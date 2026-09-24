"""Gateway-root lease authority. SQLite durability + inherited POSIX flock fence.

Never unlink/replace the lock while backends or gh children are alive.
Only metadata lives here; credentials stay in profile-bound child environments.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time

from fastapi import HTTPException

TTL = 3600


def valid_key(key):
    return isinstance(key, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', key)


def changed():
    return HTTPException(409, 'GitHub account scope changed')


def private_file(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        os.close(fd)
        raise OSError('Unsafe authority file')
    return fd


@contextmanager
def locked():
    from hermes_constants import get_default_hermes_root
    directory = get_default_hermes_root().resolve() / 'githermes-authority'
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise OSError('Unsafe authority directory')
    fd = private_file(directory / 'fence.lock')
    db = None
    try:
        # Nonblocking retries bound worker occupancy. A timeout is uncertainty,
        # never evidence that a lease is gone.
        deadline = time.monotonic() + 55
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise HTTPException(503, 'GitHub authority busy') from None
                time.sleep(.02)
        path = directory / 'leases.sqlite3'
        os.close(private_file(path))
        db = sqlite3.connect(path, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY, value TEXT NOT NULL)')
        db.execute('INSERT OR IGNORE INTO metadata VALUES (1, ?)', (secrets.token_urlsafe(24),))
        db.execute('CREATE TABLE IF NOT EXISTS leases (lease TEXT PRIMARY KEY, home TEXT NOT NULL, epoch INTEGER NOT NULL, login TEXT, touched REAL NOT NULL)')
        yield Store(db, fd)
    finally:
        if db is not None:
            db.close()
        # close, NOT LOCK_UN: an inherited child fd keeps the fence on crash.
        os.close(fd)


class Store:
    def __init__(self, db, fd):
        self.db, self.fd = db, fd
        self.backend = db.execute('SELECT value FROM metadata WHERE id=1').fetchone()[0]

    def get(self, key):
        if not valid_key(key):
            raise ValueError()
        row = self.db.execute('SELECT * FROM leases WHERE lease=?', (key,)).fetchone()
        return dict(row) if row else None

    def save(self, lease):
        self.db.execute('INSERT OR REPLACE INTO leases VALUES (:lease,:home,:epoch,:login,:touched)', lease)

    def check(self, key, home, epoch):
        lease = self.get(key)
        if not lease or lease['home'] != home or lease['epoch'] != epoch or lease['login'] is None or time.time() - lease['touched'] > TTL:
            raise changed()
        lease['touched'] = time.time()
        self.save(lease)
        return lease

    def revoke(self, key):
        lease = self.get(key)
        if not lease:
            self.db.execute('DELETE FROM leases WHERE touched < ?', (time.time() - TTL,))
            if self.db.execute('SELECT count(*) FROM leases').fetchone()[0] >= 512:
                raise HTTPException(429, 'Too many GitHub clients')
            lease = dict(lease=key, home='', epoch=secrets.randbits(48) + 1, login=None, touched=time.time())
            self.save(lease)
            return {'lease': key, 'epoch': lease['epoch'], 'reset': True}
        # Possession of this client capability may always revoke, including an
        # uncertain/lost selection reply. No other client's lease is affected.
        lease.update(epoch=lease['epoch'] + 1, login=None, touched=time.time())
        self.save(lease)
        return {k: lease[k] for k in ('lease', 'epoch')}

    def select(self, data, home):
        key = data.get('lease') or secrets.token_urlsafe(32)
        lease = self.get(key)
        if lease:
            if lease['epoch'] != data.get('epoch') or time.time() - lease['touched'] > TTL:
                raise changed()
            epoch = lease['epoch'] + 1
        else:
            if data.get('epoch', 0) != 0:
                raise changed()
            self.db.execute('DELETE FROM leases WHERE touched < ?', (time.time() - TTL,))
            if self.db.execute('SELECT count(*) FROM leases').fetchone()[0] >= 512:
                raise HTTPException(429, 'Too many GitHub clients')
            # Random initial epochs prevent ABA even after expiry/deletion.
            epoch = secrets.randbits(48) + 1
        lease = dict(lease=key, home=home, epoch=epoch, login=None, touched=time.time())
        self.save(lease)
        return lease

    def complete(self, reserved, login):
        lease = self.get(reserved['lease'])
        if not lease or lease['epoch'] != reserved['epoch'] or lease['home'] != reserved['home'] or time.time() - lease['touched'] > TTL:
            raise changed()
        lease.update(login=login, touched=time.time())
        self.save(lease)
        return {k: lease[k] for k in ('lease', 'epoch', 'login')} | {'backend': self.backend}
