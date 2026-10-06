"""Thin IMAP wrapper (feature 002 research R1, R7).

Reads with BODY.PEEK (never marks mail as read), creates folders, moves messages (UID MOVE with
COPY/EXPUNGE fallback) and appends copies to Sent. Folder names are handled decoded in Python and
encoded with IMAP modified UTF-7 on the wire.
"""

import base64
import contextlib
import imaplib
import re
import ssl
import time
from typing import Protocol

TIMEOUT_SECONDS = 30
_LIST_RE = re.compile(rb'\((?P<flags>[^)]*)\) (?P<delim>"[^"]*"|NIL) (?P<name>.+)$')


class ImapError(Exception):
    pass


# --- modified UTF-7 (RFC 3501 5.1.3) -----------------------------------------------------------


def encode_folder(name: str) -> str:
    out, buf = [], []

    def flush():
        if buf:
            data = "".join(buf).encode("utf-16-be")
            out.append("&" + base64.b64encode(data).decode().rstrip("=").replace("/", ",") + "-")
            buf.clear()

    for ch in name:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def decode_folder(name: str) -> str:
    def repl(m: re.Match) -> str:
        chunk = m.group(1)
        if chunk == "":
            return "&"
        data = chunk.replace(",", "/")
        data += "=" * (-len(data) % 4)
        return base64.b64decode(data).decode("utf-16-be")

    return re.sub(r"&([^-]*)-", repl, name)


def _quote(name: str) -> str:
    encoded = encode_folder(name)
    return '"' + encoded.replace("\\", "\\\\").replace('"', '\\"') + '"'


class Mailbox(Protocol):
    delimiter: str

    def list_folders(self) -> list[str]: ...
    def select(self, folder: str) -> int: ...
    def uids_after(self, last_uid: int) -> list[int]: ...
    def fetch(self, uid: int) -> bytes | None: ...
    def has_uid(self, uid: int) -> bool: ...
    def ensure_folder(self, folder: str) -> None: ...
    def move(self, uid: int, dest: str) -> None: ...
    def append(self, folder: str, raw: bytes) -> None: ...
    def close(self) -> None: ...


class ImapMailbox:
    """A logged-in IMAP session. Use `connect(...)` to create one."""

    def __init__(self, conn: imaplib.IMAP4):
        self._conn = conn
        self.delimiter = "/"
        self._capabilities = {c.upper() for c in getattr(conn, "capabilities", ())}
        self.list_folders()

    def _ok(self, result, what: str):
        typ, data = result
        if typ != "OK":
            raise ImapError(f"{what} failed")
        return data

    def list_folders(self) -> list[str]:
        folders = []
        for line in self._ok(self._conn.list(), "LIST"):
            if not isinstance(line, bytes):
                continue
            m = _LIST_RE.match(line)
            if not m:
                continue
            delim = m.group("delim")
            if delim != b"NIL":
                self.delimiter = delim.strip(b'"').decode() or "/"
            name = m.group("name").strip().strip(b'"').decode("ascii", "replace")
            folders.append(decode_folder(name))
        return folders

    def select(self, folder: str) -> int:
        self._ok(self._conn.select(_quote(folder)), f"SELECT {folder}")
        data = self._ok(self._conn.status(_quote(folder), "(UIDVALIDITY)"), "STATUS")
        m = re.search(rb"UIDVALIDITY (\d+)", data[0] or b"")
        return int(m.group(1)) if m else 0

    def uids_after(self, last_uid: int) -> list[int]:
        data = self._ok(self._conn.uid("SEARCH", None, f"UID {last_uid + 1}:*"), "SEARCH")
        uids = [int(x) for x in (data[0] or b"").split()]
        return sorted(u for u in uids if u > last_uid)  # "*" may return the last message

    def fetch(self, uid: int) -> bytes | None:
        data = self._ok(self._conn.uid("FETCH", str(uid), "(BODY.PEEK[])"), "FETCH")
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2:
                return item[1]
        return None

    def has_uid(self, uid: int) -> bool:
        data = self._ok(self._conn.uid("SEARCH", None, f"UID {uid}"), "SEARCH")
        return str(uid).encode() in (data[0] or b"").split()

    def ensure_folder(self, folder: str) -> None:
        if folder in self.list_folders():
            return
        typ, _ = self._conn.create(_quote(folder))
        if typ != "OK" and folder not in self.list_folders():
            raise ImapError(f"CREATE {folder} failed")
        self._conn.subscribe(_quote(folder))

    def move(self, uid: int, dest: str) -> None:
        self.ensure_folder(dest)
        if "MOVE" in self._capabilities:
            self._ok(self._conn.uid("MOVE", str(uid), _quote(dest)), "MOVE")
            return
        self._ok(self._conn.uid("COPY", str(uid), _quote(dest)), "COPY")
        self._ok(self._conn.uid("STORE", str(uid), "+FLAGS", "(\\Deleted)"), "STORE")
        self._conn.expunge()

    def append(self, folder: str, raw: bytes) -> None:
        self.ensure_folder(folder)
        when = imaplib.Time2Internaldate(time.time())
        self._ok(self._conn.append(_quote(folder), "(\\Seen)", when, raw), "APPEND")

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._conn.logout()


def connect(host: str, port: int, username: str, password: str) -> ImapMailbox:
    conn = imaplib.IMAP4_SSL(
        host, port, ssl_context=ssl.create_default_context(), timeout=TIMEOUT_SECONDS
    )
    try:
        conn.login(username, password)
    except imaplib.IMAP4.error as exc:
        conn.logout()
        raise ImapError("login rejected") from exc
    return ImapMailbox(conn)
