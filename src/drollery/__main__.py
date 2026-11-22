"""Command line tools, run inside the container:  docker compose exec drollery python -m drollery <command>

  restore FILE [--check]      restore a backup (made under Settings > Backup) into a library that has no account yet.
                              The file is checked first and nothing is changed if it does not pass. With --check it
                              only checks the file and says what is in it, and touches nothing.
  reset-admin [--user NAME]   set a new one-time password for the account, turn its two-factor authentication off and
                              sign it out everywhere. Use it when you cannot sign in any more. Needs access to the
                              server, which is the point: whoever can run it already controls the data.
"""
from __future__ import annotations

import argparse
import sys

from pathlib import Path

from . import accounts, db, restore, security


def reset_admin(username: str = "", out=print) -> int:
    db.init()
    with db.tx() as c:
        users = [dict(r) for r in c.execute("SELECT id, username, role FROM users ORDER BY id")]
    if not users:
        out("No account exists yet. Open Drollery in the browser and create it with the setup code from `docker compose logs drollery`.")
        return 1
    if username:
        user = next((u for u in users if u["username"].lower() == username.strip().lower()), None)
        if not user:
            out(f"There is no account called “{username}”. Accounts: " + ", ".join(u["username"] for u in users))
            return 1
    elif len(users) == 1:
        user = users[0]
    else:
        out("There is more than one account, so say which one: --user NAME. Accounts: " + ", ".join(u["username"] for u in users))
        return 1
    password = security.new_token(12)                     # 16 characters, comfortably above the minimum
    accounts.set_password(user["id"], password)
    accounts.disable_2fa(user["id"])
    accounts.delete_user_sessions(user["id"])
    out(f"New password for “{user['username']}”: {password}")
    out("Sign in with it, then change it under Settings > Security (and switch two-factor authentication on again).")
    out("Two-factor authentication was turned off and every browser was signed out. If the sign-in page still says "
        "“too many attempts”, wait 15 minutes or run: docker compose restart drollery")
    return 0


def restore_backup(path: str, check: bool = False, out=print) -> int:
    file = Path(path)
    if not file.is_file():
        out(f"There is no file {path}. With Docker, put the backup in the folder you mount, for example -v \"$PWD\":/backup")
        return 1
    if not check:
        db.init()                                               # a fresh volume has no tables yet
    try:
        with file.open("rb") as f:
            summary = restore.restore(f, apply=not check)
    except restore.RestoreError as e:
        out(str(e))
        return 1
    facts = f"{summary.items} items, {summary.people} people, {summary.users} accounts"
    missing = f" {summary.no_file} items have no file{' yet' if not check else ''}." if summary.no_file else ""
    if check:
        out(f"This backup is fine and can be restored: {facts}.{missing}")
    else:
        out(f"Restored: {facts}.{missing}")
        out("Start Drollery and sign in with an account from the backup. A restored config.toml applies after a restart "
            "(the one that was there before is kept as config.toml.before-restore).")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m drollery", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("restore", help="restore a backup into a library that has no account yet")
    b.add_argument("file", help="the .tgz from Settings > Backup")
    b.add_argument("--check", action="store_true", help="only check the file and say what is in it")
    r = sub.add_parser("reset-admin", help="set a new one-time password and turn two-factor authentication off")
    r.add_argument("--user", default="", help="the account, when there is more than one")
    args = p.parse_args(argv)
    if args.command == "restore":
        return restore_backup(args.file, args.check)
    return reset_admin(args.user)


if __name__ == "__main__":
    sys.exit(main())
