"""Administration CLI.

    python -m oqumap.admin create-org --name "Сеть школ" --admin alice
        (password from the OQUMAP_ADMIN_PASSWORD environment variable or an interactive prompt)
"""

from __future__ import annotations

import argparse
import getpass
import json
import os

from .db import session_factory
from .services.admin import create_organization


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-org")
    c.add_argument("--name", required=True)
    c.add_argument("--admin", required=True)
    c.add_argument("--display-name")
    a = ap.parse_args()
    pw = os.environ.get("OQUMAP_ADMIN_PASSWORD") or getpass.getpass("Пароль администратора: ")
    with session_factory()() as s:
        org, user = create_organization(s, a.name, a.admin, pw, a.display_name)
        print(json.dumps({"org_id": org.id, "admin_user_id": user.id, "username": user.username}, ensure_ascii=False))


if __name__ == "__main__":
    main()
