"""Command line tools, run inside the container:  docker compose exec drollery python -m drollery <command>

  reset-admin [--user NAME]   set a new one-time password for the account, turn its two-factor authentication off and
                              sign it out everywhere. Use it when you cannot sign in any more. Needs access to the
                              server, which is the point: whoever can run it already controls the data.
"""
from __future__ import annotations

import argparse
import sys

from . import accounts, db, security


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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m drollery", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("reset-admin", help="set a new one-time password and turn two-factor authentication off")
    r.add_argument("--user", default="", help="the account, when there is more than one")
    args = p.parse_args(argv)
    return reset_admin(args.user)


if __name__ == "__main__":
    sys.exit(main())
