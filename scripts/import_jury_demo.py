#!/usr/bin/env python3
"""Import a NEW isolated jury project through existing authenticated APIs.

Requires OQUMAP_TOKEN (methodist) and --url. Never resets or deletes an existing project.
PDF/source linking requires the separate local adapter documented in README.
"""

import argparse
import os
import time
from pathlib import Path

import httpx
from generate_jury_demo import OUT
from jury_demo_support import validate_files


def import_project(client, root, name):
    def call(method, path, **kwargs):
        response = getattr(client, method)("/api/v1" + path, **kwargs)
        response.raise_for_status()
        return response.json()

    def completed(job):
        for _ in range(120):
            if job["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.25)
            job = call("get", f"/jobs/{job['id']}")
        if job["status"] != "succeeded":
            raise RuntimeError(
                f"Job did not succeed: {job.get('error') or job['status']}"
            )
        return job

    validate_files(root)
    ds = call("post", "/datasets", json={"name_ru": name, "is_synthetic": True})
    print(f"Created dataset {ds['id']}; retain this ID to resume after any error.")
    for n, kind in enumerate(
        ("program", "editions", "item_bank", "roster", "responses"), 1
    ):
        file = f"{n}_{kind}.csv"
        validated = call(
            "post",
            "/imports/validate",
            files={"file": (file, (root / file).read_bytes(), "text/csv")},
            data={"dataset_id": ds["id"], "kind": kind},
        )
        if validated["rows_rejected"] or not validated["report"].get(
            "commit_allowed", True
        ):
            raise RuntimeError(f"Import blocked for {kind}: {validated['report']}")
        completed(
            call(
                "post",
                "/imports/commit",
                json={"batch_id": validated["id"], "wait": True},
            )
        )
        print(f"{kind}: {validated['rows_accepted']} accepted; 0 rejected")
    cur = call("get", "/curriculum", params={"dataset_id": ds["id"]})
    editions = {e["code"]: e["id"] for e in cur["editions"]}
    for ed in "AB":
        name = f"textbook_{ed}.pdf"
        uploaded = call(
            "post",
            "/documents",
            files={
                "file": (
                    name,
                    (root / "materials" / name).read_bytes(),
                    "application/pdf",
                )
            },
            data={"edition_id": editions[f"JURY-{ed}"]},
        )
        completed(uploaded["job"])
        print(f"{name}: extracted")
    print(f"Next: python scripts/load_jury_material_links.py --dataset-id {ds['id']}")
    return ds["id"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True)
    p.add_argument("--root", type=Path, default=OUT)
    p.add_argument("--name", default="OquMap Jury - Математика 6 (synthetic)")
    args = p.parse_args()
    token = os.environ.get("OQUMAP_TOKEN")
    if not token:
        p.error(
            "Set OQUMAP_TOKEN; do not put tokens in command arguments or committed files."
        )
    with httpx.Client(
        base_url=args.url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=180,
    ) as client:
        import_project(client, args.root, args.name)


if __name__ == "__main__":
    main()
