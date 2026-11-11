#!/usr/bin/env python3
"""Attach reviewed synthetic fixture links after normal CSV + PDF import.

Run in the backend environment with OQUMAP_DATABASE_URL set, passing the imported dataset ID.
Does not import intervention fixtures, create users, seed demo tenants or modify analytics.
"""

import argparse
import os
from pathlib import Path

from generate_jury_demo import OUT
from jury_demo_support import connect_material_links, validate_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--root", type=Path, default=OUT)
    args = parser.parse_args()
    if not os.environ.get("OQUMAP_DATABASE_URL"):
        parser.error(
            "Set OQUMAP_DATABASE_URL explicitly to the backend database. No default connection is used."
        )
    from oqumap import db

    validate_files(args.root)
    db.configure(os.environ["OQUMAP_DATABASE_URL"])
    with db.session_factory()() as session:
        count = connect_material_links(session, args.dataset_id, args.root)
    print(f"Attached {count} synthetic source links (idempotent).")


if __name__ == "__main__":
    main()
