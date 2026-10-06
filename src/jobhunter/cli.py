"""Command-line tools run inside the container (contracts/cli-and-config.md)."""

import argparse
import getpass
import sqlite3
import sys
from pathlib import Path

from sqlmodel import Session, select

from jobhunter.auth.passwords import (
    PolicyError,
    hash_password,
    validate_password,
    validate_username,
)
from jobhunter.config import get_settings
from jobhunter.db import get_engine
from jobhunter.models import Role, UserAccount


def _prompt_password() -> str:
    first = getpass.getpass("Password (min 12 characters): ")
    second = getpass.getpass("Repeat password: ")
    if first != second:
        raise PolicyError("Passwords do not match.")
    return validate_password(first)


def create_admin(
    username: str, display_name: str, seed_defaults: bool, password: str | None = None
) -> int:
    return create_account(username, display_name, Role.ADMIN, seed_defaults, password)


def create_account(
    username: str,
    display_name: str,
    role: Role,
    seed_defaults: bool = False,
    password: str | None = None,
) -> int:
    try:
        validate_username(username)
        if not display_name.strip():
            raise PolicyError("Display name is required.")
        password = validate_password(password) if password is not None else _prompt_password()
    except PolicyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    with Session(get_engine()) as db:
        if db.exec(select(UserAccount).where(UserAccount.username == username)).first():
            print(f"error: user '{username}' already exists", file=sys.stderr)
            return 1
        user = UserAccount(
            username=username,
            display_name=display_name.strip(),
            role=role.value,
            password_hash=hash_password(password),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        if seed_defaults:
            from jobhunter.seeds import apply_first_admin_defaults

            added = apply_first_admin_defaults(db, user)
            print("seeded: " + ", ".join(added))
    print(f"created {role.value} '{username}'")
    return 0


def set_password(username: str, password: str | None = None) -> int:
    """Reset a user's password and end their sessions (until the admin page exists)."""
    from jobhunter.auth.sessions import delete_sessions_for_user

    try:
        password = validate_password(password) if password is not None else _prompt_password()
    except PolicyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    with Session(get_engine()) as db:
        user = db.exec(select(UserAccount).where(UserAccount.username == username)).first()
        if user is None:
            print(f"error: no user '{username}'", file=sys.stderr)
            return 1
        user.password_hash = hash_password(password)
        db.add(user)
        db.commit()
        delete_sessions_for_user(db, user.id)
    print(f"password updated for '{username}'")
    return 0


def seed_defaults(username: str) -> int:
    """Add the default starting data to an existing account."""
    from jobhunter.seeds import SeedError, apply_first_admin_defaults

    with Session(get_engine()) as db:
        user = db.exec(select(UserAccount).where(UserAccount.username == username)).first()
        if user is None:
            print(f"error: no user '{username}'", file=sys.stderr)
            return 1
        try:
            added = apply_first_admin_defaults(db, user)
        except SeedError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    print(f"seeded for '{username}': " + ", ".join(added))
    return 0


def backup(dest: str) -> int:
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(get_settings().database_path)
    try:
        out = sqlite3.connect(dest_path)
        with out:
            src.backup(out)
        out.close()
    finally:
        src.close()
    print(dest_path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobhunter")
    sub = parser.add_subparsers(dest="command", required=True)

    p_admin = sub.add_parser("create-admin", help="create an admin account")
    p_admin.add_argument("username")
    p_admin.add_argument("--display-name", required=True)
    p_admin.add_argument(
        "--seed-defaults",
        action="store_true",
        help="add the default QA Lead profile and sender settings",
    )

    p_user = sub.add_parser(
        "create-user", help="create a regular (non-admin) account until the admin page exists"
    )
    p_user.add_argument("username")
    p_user.add_argument("--display-name", required=True)

    p_pw = sub.add_parser("set-password", help="reset a user's password")
    p_pw.add_argument("username")

    p_seed = sub.add_parser(
        "seed-defaults", help="add the default QA Lead profile and sender settings to a user"
    )
    p_seed.add_argument("username")

    p_backup = sub.add_parser("backup", help="online backup of the SQLite database")
    p_backup.add_argument("dest")

    args = parser.parse_args(argv)
    if args.command == "create-admin":
        return create_admin(args.username, args.display_name, args.seed_defaults)
    if args.command == "seed-defaults":
        return seed_defaults(args.username)
    if args.command == "set-password":
        return set_password(args.username)
    if args.command == "create-user":
        return create_account(args.username, args.display_name, Role.USER)
    return backup(args.dest)


if __name__ == "__main__":
    sys.exit(main())
