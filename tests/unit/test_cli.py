from sqlmodel import select

from jobhunter.cli import create_account, create_admin
from jobhunter.models import Role, UserAccount

PW = "a long enough password"


def _user(session, name):
    return session.exec(select(UserAccount).where(UserAccount.username == name)).one()


def test_create_admin_and_user(session):
    assert create_admin("sam", "Sam Rivera", False, password=PW) == 0
    assert create_account("robin", "Robin", Role.USER, password=PW) == 0
    assert _user(session, "sam").role == "admin"
    robin = _user(session, "robin")
    assert robin.role == "user" and robin.is_active and not robin.must_change_password


def test_rejects_bad_username_short_password_and_duplicates(session):
    assert create_account("Robin!", "Robin", Role.USER, password=PW) == 1
    assert create_account("robin", "Robin", Role.USER, password="short") == 1
    assert create_account("robin", "Robin", Role.USER, password=PW) == 0
    assert create_account("robin", "Robin", Role.USER, password=PW) == 1


def test_set_password(session):
    from jobhunter.auth.passwords import verify_password
    from jobhunter.cli import set_password

    create_account("robin", "Robin", Role.USER, password=PW)
    assert set_password("robin", password="another long password") == 0
    session.expire_all()
    assert verify_password("another long password", _user(session, "robin").password_hash)
    assert set_password("nobody", password="another long password") == 1
    assert set_password("robin", password="short") == 1


def test_notify_admins_reaches_admins_with_a_chat_id(session):
    from jobhunter.cli import notify_admins
    from jobhunter.models import NotificationSettings
    from jobhunter.services.telegram import Result

    assert create_admin("sam", "Sam Rivera", False, password=PW) == 0
    assert create_admin("kim", "Kim Lee", False, password=PW) == 0
    assert create_account("robin", "Robin", Role.USER, password=PW) == 0
    sent = []

    def fake_send(chat, text):
        sent.append((chat, text))
        return Result(True, "Sent.")

    assert notify_admins("Backup failed", send=fake_send) == 1  # nobody has a chat id yet
    for name, chat, reminders in (("sam", "111", False), ("kim", "", True), ("robin", "333", True)):
        session.add(
            NotificationSettings(
                user_id=_user(session, name).id, telegram_chat_id=chat, reminders_enabled=reminders
            )
        )
    session.commit()
    # only admins with a chat id; sent even though sam turned daily reminders off
    assert notify_admins("Backup failed", send=fake_send) == 0
    assert sent == [("111", "Backup failed")]
    assert notify_admins("x", send=lambda chat, text: Result(False, "Telegram rejected")) == 1
