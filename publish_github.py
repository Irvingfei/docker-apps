#!/usr/bin/env python3
"""Create one public GitHub repository per app and publish its Release assets.

Requires GITHUB_TOKEN with repo scope (and GITHUB_OWNER, default Irvingfei).
Dry-run by default; pass --apply to create repositories and upload releases.
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request

from build import APPS, ARCHES, DIST, VERSION

API = "https://api.github.com"
UPLOAD = "https://uploads.github.com"


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
OWNER = os.environ.get("GITHUB_OWNER", "Irvingfei")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
TAG = "v" + VERSION


def call(method, url, payload=None, raw=None, ctype="application/json"):
    body = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", ctype)
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "tos-docker-apps")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode()
        try:
            return exc.code, json.loads(raw_body or "{}")
        except ValueError:
            return exc.code, {"raw": raw_body[:400]}


REPO_OVERRIDES = {"coder-code-server": "code-server"}


def repo_name(app_id):
    return "tos-" + REPO_OVERRIDES.get(app_id, app_id)


def repo_readme(app_id):
    app = APPS[app_id]
    return """# %s for TOS 7 (Docker)

%s

%s

## Package

- Application ID: `%s`
- Type: Docker (TOS 7)
- Architecture: `x86_64`, `aarch64`
- Upstream image: see `docker-compose.yml` in the downloaded asset
- Web UI port: declared in `x-app-meta`

## Source

The `src/` directory contains the files the package is built from:

- `src/config.x86_64.ini` / `src/config.aarch64.ini` — `config.ini` per architecture
- `src/docker-compose.yml` — compose template; `@@...@@` placeholders are replaced at build time
- `src/%s.lang` — 14 language sections
- `src/%s.svg` — application icon

Build toolchain: https://github.com/Irvingfei/tos-docker-apps

## Install

1. In the TOS App Center, add this repository's application and submit the matching `%s_<arch>.tar.gz` asset from the latest Release.
2. Data is stored under `/Volume<N>/DockerAppData/%s/` through the compose bind mounts.

## Notes

%s

This repository packages the upstream open-source application for TerraMaster TOS 7.
It is not affiliated with or endorsed by the upstream project. Application names and
trademarks belong to their respective owners. All images are pulled from Docker Hub.
""" % (app["name"], app["descript"]["zh-cn"], app["descript"]["en-us"], app_id, app_id, app_id, app_id, app_id,
       app["important"]["zh-cn"])


def ensure_repo(app_id, apply):
    name = repo_name(app_id)
    status, body = call("GET", "%s/repos/%s/%s" % (API, OWNER, name))
    if status == 200:
        print("repo exists: %s/%s" % (OWNER, name))
        return body
    if status != 404:
        print("repo lookup failed: http %s %s" % (status, body))
        return None
    print("create repo: %s/%s" % (OWNER, name))
    if not apply:
        return None
    status, body = call("POST", "%s/user/repos" % API, {
        "name": name,
        "description": "%s packaged for TerraMaster TOS 7 (Docker)" % APPS[app_id]["name"],
        "private": False,
        "has_issues": False,
        "has_wiki": False,
        "auto_init": False,
    })
    if status not in (200, 201):
        print("create failed: http %s %s" % (status, body))
        return None
    content = base64.b64encode(repo_readme(app_id).encode()).decode()
    status, body = call("PUT", "%s/repos/%s/%s/contents/README.md" % (API, OWNER, name), {
        "message": "Add README",
        "content": content,
    })
    print("readme: http %s" % status)
    return {"name": name}


def ensure_release(app_id, apply):
    name = repo_name(app_id)
    status, rel = call("GET", "%s/repos/%s/%s/releases/tags/%s" % (API, OWNER, name, TAG))
    if status == 200:
        print("release exists: %s" % TAG)
        return rel
    print("create release: %s %s" % (name, TAG))
    if not apply:
        return None
    body = "\n".join([
        "%s %s" % (APPS[app_id]["name"], VERSION),
        "",
        APPS[app_id]["release_note"],
        "",
        "Assets: x86_64 and aarch64 Docker application packages with SHA-256 checksums.",
    ])
    status, rel = call("POST", "%s/repos/%s/%s/releases" % (API, OWNER, name), {
        "tag_name": TAG,
        "target_commitish": "main",
        "name": "%s %s" % (APPS[app_id]["name"], VERSION),
        "body": body,
        "draft": False,
        "prerelease": False,
    })
    if status not in (200, 201):
        print("release failed: http %s %s" % (status, rel))
        return None
    return rel


def publish_assets(app_id, rel, apply, replace=False):
    name = repo_name(app_id)
    existing = {}
    if rel:
        status, assets = call("GET", "%s/repos/%s/%s/releases/%s/assets" % (API, OWNER, name, rel["id"]))
        if status == 200:
            existing = {a["name"]: a["id"] for a in assets}
    for arch in ARCHES:
        for suffix in ("", ".sha256"):
            filename = "%s_%s.tar.gz%s" % (app_id, arch, suffix)
            if filename in existing:
                if not replace:
                    print("skip existing asset: %s" % filename)
                    continue
                print("replace asset: %s" % filename)
                if not apply:
                    continue
                status, _ = call("DELETE", "%s/repos/%s/%s/releases/assets/%s" % (
                    API, OWNER, name, existing[filename]))
                if status not in (200, 204):
                    print("  delete failed: http %s" % status)
                    continue
            else:
                print("upload asset: %s" % filename)
                if not apply:
                    continue
            path = os.path.join(DIST, app_id, filename)
            with open(path, "rb") as fh:
                data = fh.read()
            ctype = "text/plain" if suffix else "application/gzip"
            status, asset = call(
                "POST",
                "%s/repos/%s/%s/releases/%s/assets?name=%s" % (UPLOAD, OWNER, name, rel["id"], filename),
                raw=data,
                ctype=ctype,
            )
            print("  http %s %s" % (status, asset.get("state", asset.get("message", ""))[:80]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="actually create repos/releases")
    parser.add_argument("--replace", action="store_true", help="re-upload assets that already exist")
    parser.add_argument("--app", action="append", help="limit to one or more app ids")
    args = parser.parse_args()

    if args.apply and not TOKEN:
        sys.exit("GITHUB_TOKEN is required for --apply")
    apps = args.app or list(APPS)
    if not TOKEN:
        for app_id in apps:
            print("%-14s repo=%s/%s release=%s assets=%s" % (
                app_id, OWNER, repo_name(app_id), TAG,
                ", ".join("%s_%s.tar.gz" % (app_id, a) for a in ARCHES)))
        print("\nno GITHUB_TOKEN: planned actions only")
        return
    for app_id in apps:
        print("\n=== %s ===" % app_id)
        repo = ensure_repo(app_id, args.apply)
        if args.apply and not repo:
            continue
        rel = ensure_release(app_id, args.apply)
        if args.apply and not rel:
            continue
        publish_assets(app_id, rel, args.apply, args.replace)
    if not args.apply:
        print("\ndry-run only; re-run with --apply to publish")


if __name__ == "__main__":
    main()
