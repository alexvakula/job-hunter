"""In-memory stand-in for jobhunter.services.imap_client.ImapMailbox."""

from pathlib import Path

FIX = Path(__file__).resolve().parent / "fixtures" / "emails"


class FakeMailbox:
    delimiter = "/"

    def __init__(self, folders: dict[str, list[bytes]] | None = None):
        self.folders: dict[str, dict[int, bytes]] = {"INBOX": {}, "Sent": {}}
        self.uidvalidity = {"INBOX": 1, "Sent": 1}
        self.next_uid: dict[str, int] = {"INBOX": 1, "Sent": 1}
        self.selected: str | None = None
        self.fetched: list[tuple[str, int]] = []
        self.moves: list[tuple[str, int, str]] = []
        self.appended: list[tuple[str, bytes]] = []
        self.closed = False
        for name, messages in (folders or {}).items():
            for raw in messages:
                self.deliver(raw, name)

    # test helpers
    def deliver(self, raw: bytes, folder: str = "INBOX") -> int:
        self.ensure_folder(folder)
        uid = self.next_uid[folder]
        self.next_uid[folder] += 1
        self.folders[folder][uid] = raw
        return uid

    def deliver_fixture(self, name: str, folder: str = "INBOX") -> int:
        return self.deliver((FIX / name).read_bytes(), folder)

    def user_moves(self, folder: str, uid: int, dest: str) -> None:
        raw = self.folders[folder].pop(uid)
        self.deliver(raw, dest)

    # Mailbox protocol
    def list_folders(self) -> list[str]:
        return list(self.folders)

    def select(self, folder: str) -> int:
        if folder not in self.folders:
            raise KeyError(folder)
        self.selected = folder
        return self.uidvalidity[folder]

    def uids_after(self, last_uid: int) -> list[int]:
        return sorted(u for u in self.folders[self.selected] if u > last_uid)

    def fetch(self, uid: int) -> bytes | None:
        self.fetched.append((self.selected, uid))
        return self.folders[self.selected].get(uid)

    def has_uid(self, uid: int) -> bool:
        return uid in self.folders[self.selected]

    def ensure_folder(self, folder: str) -> None:
        if folder not in self.folders:
            self.folders[folder] = {}
            self.uidvalidity[folder] = 1
            self.next_uid[folder] = 1

    def move(self, uid: int, dest: str) -> None:
        raw = self.folders[self.selected].pop(uid)
        self.deliver(raw, dest)
        self.moves.append((self.selected, uid, dest))

    def append(self, folder: str, raw: bytes) -> None:
        self.deliver(raw, folder)
        self.appended.append((folder, raw))

    def close(self) -> None:
        self.closed = True
