#!/usr/bin/env python3
"""Create TOS Developer Platform apps and submit their Docker versions.

Requires TDP_TOKEN. Dry-run by default; pass --apply to create apps and versions.
The GitHub Releases must already exist (see publish_github.py).
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

from build import APPS, ARCHES, VERSION

BASE = os.environ.get("TDP_BASE_URL") or os.environ.get("TDP_BASE", "https://api-developer.terra-master.com")


def _load_env():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


_load_env()
TOKEN = os.environ.get("TDP_TOKEN") or os.environ.get("TDP_API_TOKEN", "")
OWNER = os.environ.get("GITHUB_OWNER", "Irvingfei")
TAG = "v" + VERSION


def call(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    last = None
    for attempt in range(4):
        req = urllib.request.Request(BASE + path, data=data, method=method)
        req.add_header("Authorization", "Bearer " + TOKEN)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode()
                return resp.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            try:
                return exc.code, (json.loads(raw) if raw.strip() else {})
            except ValueError:
                return exc.code, {"raw": raw[:400]}
        except urllib.error.URLError as exc:
            last = exc
            print("  network error (attempt %d): %s" % (attempt + 1, exc.reason), flush=True)
            time.sleep(2 * (attempt + 1))
    return 0, {"error": str(last)}


REPO_OVERRIDES = {"coder-code-server": "code-server"}


def repo_url(app_id):
    return "https://github.com/%s/tos-%s" % (OWNER, REPO_OVERRIDES.get(app_id, app_id))


def asset_url(app_id, arch):
    return "%s/releases/download/%s/%s_%s.tar.gz" % (repo_url(app_id), TAG, app_id, arch)


def find_app(records, app_id, arch):
    for item in records:
        kind = item.get("kind")
        if kind == "docker image":
            kind = "docker"
        if item.get("app_id") == app_id and kind == "docker" and item.get("platform") == arch:
            return item
    return None


def ensure_app(records, app_id, arch, apply):
    existing = find_app(records, app_id, arch)
    if existing:
        print("app exists: %s/%s -> %s" % (app_id, arch, existing.get("id")))
        return existing
    print("create app: %s (%s) repo=%s" % (app_id, arch, repo_url(app_id)))
    if not apply:
        return None
    status, body = call("POST", "/v1/apps", {
        "app_id": app_id,
        "kind": "docker",
        "platform": arch,
        "repo": repo_url(app_id),
    })
    if status not in (200, 201):
        print("create app failed: http %s %s" % (status, body))
        return None
    print("created app uuid=%s" % body.get("id"))
    return body


def wait_task(app_uuid, task_id):
    for _ in range(180):
        status, body = call("GET", "/v1/apps/%s/versions/tasks/%s" % (app_uuid, task_id))
        all_status = body.get("all_status")
        print("  poll http=%s all_status=%s" % (status, all_status), flush=True)
        if all_status == 2:
            return True
        if all_status == 3:
            print(json.dumps(body, ensure_ascii=False)[:1500])
            return False
        time.sleep(5)
    print("  task timed out")
    return False


def submit_version(app_uuid, app_id, arch, apply):
    url = asset_url(app_id, arch)
    print("submit version: %s -> %s" % (TAG, url))
    if not apply:
        return
    status, body = call("POST", "/v1/apps/%s/versions" % app_uuid, {
        "tag": TAG,
        "browser_download_url": url,
    })
    if status not in (200, 202):
        print("create version failed: http %s %s" % (status, body))
        return
    task_id = body.get("task_id")
    if not task_id:
        print("no task_id in response: %s" % body)
        return
    if not wait_task(app_uuid, task_id):
        return
    status, result = call("GET", "/v1/apps/%s/versions/tasks/%s/result" % (app_uuid, task_id))
    print("  parsed: http %s version=%s platform=%s hash=%s" % (
        status, result.get("version_number"), result.get("platform"), str(result.get("file_hash"))[:16]))
    status, version = call("POST", "/v1/apps/%s/versions/tasks/%s/confirm" % (app_uuid, task_id))
    print("  confirm: http %s version_id=%s" % (status, version.get("id")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--app", action="append")
    parser.add_argument("--arch", action="append", choices=ARCHES)
    args = parser.parse_args()

    if args.apply and not TOKEN:
        sys.exit("TDP_TOKEN is required for --apply")

    apps = args.app or list(APPS)
    arches = args.arch or ARCHES

    if not TOKEN:
        for app_id in apps:
            for arch in arches:
                print("%-14s %-8s repo=%s asset=%s" % (
                    app_id, arch, repo_url(app_id), asset_url(app_id, arch)))
        print("\nno TDP_TOKEN: planned actions only")
        return

    status, records = call("GET", "/v1/apps?kind=all")
    if status != 200 or not isinstance(records, list):
        sys.exit("cannot list apps: http %s %s" % (status, records))

    for app_id in apps:
        for arch in arches:
            print("\n=== %s / %s ===" % (app_id, arch))
            app = ensure_app(records, app_id, arch, args.apply)
            if args.apply and not app:
                continue
            submit_version(app["id"], app_id, arch, args.apply)
            if args.apply:
                status, records = call("GET", "/v1/apps?kind=all")
    if not args.apply:
        print("\ndry-run only; re-run with --apply after GitHub Releases exist")


if __name__ == "__main__":
    main()
