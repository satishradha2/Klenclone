from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
from zipfile import ZipFile

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Download verified permission-scoped UAT review packages")
    parser.add_argument("--base-url", default="http://127.0.0.1:18082")
    parser.add_argument("--username", default="synthetic.uat.reader")
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    password = os.getenv("KLEN_UAT_PASSWORD")
    if not password:
        raise SystemExit("KLEN_UAT_PASSWORD is required")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output_dir or f"var/business_review_packages/{stamp}").resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    index = {"generated_at": datetime.now(timezone.utc).isoformat(), "base_url": args.base_url,
             "username": args.username, "packages": [], "posting_enabled": False}
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=60) as client:
        login = client.post("/api/v1/auth/login", json={"username": args.username, "password": password})
        login.raise_for_status()
        csrf_token = login.json()["csrf_token"]
        catalog = client.get("/api/v1/secure/export-catalog")
        catalog.raise_for_status()
        for item in catalog.json()["items"]:
            response = client.get(item["package_path"])
            response.raise_for_status()
            digest = hashlib.sha256(response.content).hexdigest()
            if digest != response.headers.get("x-content-sha256"):
                raise RuntimeError(f"Checksum mismatch for {item['module']}")
            disposition = response.headers.get("content-disposition", "")
            filename = disposition.split('filename="', 1)[-1].rstrip('"')
            target = output_dir / filename
            if target.exists():
                raise FileExistsError(f"Refusing to overwrite {target}")
            with ZipFile(BytesIO(response.content)) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                if manifest["module"] != item["module"] or manifest["source_or_clone_mutated"] is not False:
                    raise RuntimeError(f"Invalid manifest for {item['module']}")
            target.write_bytes(response.content)
            index["packages"].append({"module": item["module"], "file": filename,
                                      "bytes": len(response.content), "sha256": digest})
        client.post("/api/v1/auth/logout", json={}, headers={"X-CSRF-Token": csrf_token}).raise_for_status()
    (output_dir / "package-index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": "complete", "output_dir": str(output_dir),
                      "package_count": len(index["packages"]), "posting_enabled": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
