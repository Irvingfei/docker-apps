#!/usr/bin/env python3
"""Upload the packaging toolchain and per-app sources to GitHub.

Creates Irvingfei/tos-docker-apps for the toolchain and commits src/ trees into
each Irvingfei/tos-<app> repository. Dry-run by default; pass --apply to write.
"""

import argparse
import base64
import hashlib
import json
import os
import sys

from build import APPS, ARCHES, ICONS, ROOT, build_config, build_lang
from publish_github import API, OWNER, TOKEN, call, repo_name, repo_readme

TOOLCHAIN_REPO = "tos-docker-apps"
TOOLCHAIN_FILES = [
    "README.md",
    "build.py",
    "publish_github.py",
    "publish_sources.py",
    "submit_tdp.py",
    ".env.example",
    ".gitignore",
]

SRC_README = """# Source

This directory holds the source files of the TOS 7 Docker package. The release
assets are built from these files.

- `config.x86_64.ini` / `config.aarch64.ini` — `config.ini` for each architecture
- `docker-compose.yml` — build template; `@@...@@` placeholders are replaced at build time
- `{lang}` — 14 language sections
- `{svg}` — application icon

Build toolchain: https://github.com/Irvingfei/tos-docker-apps
"""


def blob_sha(content):
    data = content.encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def ensure_repo(name, description, apply):
    status, body = call("GET", "%s/repos/%s/%s" % (API, OWNER, name))
    if status == 200:
        return body
    if status != 404:
        print("repo lookup failed: http %s %s" % (status, body))
        return None
    print("create repo: %s/%s" % (OWNER, name))
    if not apply:
        return {"name": name, "default_branch": "main"}
    status, body = call("POST", "%s/user/repos" % API, {
        "name": name,
        "description": description,
        "private": False,
        "has_issues": False,
        "has_wiki": False,
        "auto_init": False,
    })
    if status not in (200, 201):
        print("create failed: http %s %s" % (status, body))
        return None
    print("created %s/%s" % (OWNER, name))
    return body


def tree_map(repo, tree_sha):
    status, body = call("GET", "%s/repos/%s/%s/git/trees/%s?recursive=1" % (API, OWNER, repo, tree_sha))
    if status != 200:
        return {}
    return {e["path"]: e["sha"] for e in body.get("tree", []) if e.get("type") == "blob"}


def bootstrap(repo, branch, files, apply):
    status, _ = call("GET", "%s/repos/%s/%s/git/ref/heads/%s" % (API, OWNER, repo, branch))
    if status == 200:
        return True
    print("  initialize repository via README")
    if not apply:
        return True
    status, body = call("PUT", "%s/repos/%s/%s/contents/README.md" % (API, OWNER, repo), {
        "message": "Initialize repository",
        "content": base64.b64encode(files["README.md"].encode("utf-8")).decode(),
    })
    if status not in (200, 201):
        print("  bootstrap failed: http %s %s" % (status, body))
        return False
    return True


def commit_files(repo, branch, files, message, apply):
    status, head = call("GET", "%s/repos/%s/%s/git/ref/heads/%s" % (API, OWNER, repo, branch))
    head_sha = None
    base_tree = None
    existing = {}
    if status == 200:
        head_sha = head["object"]["sha"]
        status, commit = call("GET", "%s/repos/%s/%s/git/commits/%s" % (API, OWNER, repo, head_sha))
        if status == 200:
            base_tree = commit["tree"]["sha"]
            existing = tree_map(repo, base_tree)

    changed = {p: c for p, c in files.items() if existing.get(p) != blob_sha(c)}
    if not changed:
        print("  source up to date")
        return True
    print("  files to commit: %s" % ", ".join(sorted(changed)))
    if not apply:
        return True

    entries = []
    for path, content in sorted(changed.items()):
        status, blob = call("POST", "%s/repos/%s/%s/git/blobs" % (API, OWNER, repo), {
            "content": content,
            "encoding": "utf-8",
        })
        if status not in (200, 201):
            print("  blob failed: %s http %s %s" % (path, status, blob))
            return False
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})

    tree_payload = {"tree": entries}
    if base_tree:
        tree_payload["base_tree"] = base_tree
    status, tree = call("POST", "%s/repos/%s/%s/git/trees" % (API, OWNER, repo), tree_payload)
    if status not in (200, 201):
        print("  tree failed: http %s %s" % (status, tree))
        return False

    commit_payload = {"message": message, "tree": tree["sha"], "parents": [head_sha] if head_sha else []}
    status, commit = call("POST", "%s/repos/%s/%s/git/commits" % (API, OWNER, repo), commit_payload)
    if status not in (200, 201):
        print("  commit failed: http %s %s" % (status, commit))
        return False
    print("  commit %s" % commit["sha"][:10])

    if head_sha:
        status, body = call("PATCH", "%s/repos/%s/%s/git/refs/heads/%s" % (API, OWNER, repo, branch), {
            "sha": commit["sha"],
            "force": False,
        })
    else:
        status, body = call("POST", "%s/repos/%s/%s/git/refs" % (API, OWNER, repo), {
            "ref": "refs/heads/%s" % branch,
            "sha": commit["sha"],
        })
    if status not in (200, 201):
        print("  ref update failed: http %s %s" % (status, body))
        return False
    return True


def app_files(app_id):
    files = {"README.md": repo_readme(app_id)}
    files["src/README.md"] = SRC_README.format(
        lang="%s.lang" % app_id, svg="%s.svg" % app_id)
    for arch in ARCHES:
        files["src/config.%s.ini" % arch] = json.dumps(
            build_config(app_id, arch), ensure_ascii=False, indent=2) + "\n"
    files["src/docker-compose.yml"] = APPS[app_id]["compose"]
    files["src/%s.lang" % app_id] = build_lang(app_id)
    files["src/%s.svg" % app_id] = ICONS[app_id]
    return files


def read_toolchain():
    files = {}
    for name in TOOLCHAIN_FILES:
        with open(os.path.join(ROOT, name), "r", encoding="utf-8") as fh:
            files[name] = fh.read()
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--app", action="append")
    parser.add_argument("--toolchain-only", action="store_true")
    args = parser.parse_args()

    if args.apply and not TOKEN:
        sys.exit("GITHUB_TOKEN is required for --apply")

    print("=== toolchain ===")
    repo = ensure_repo(TOOLCHAIN_REPO,
                       "TOS 7 Docker app packaging toolchain (config.ini, compose, lang, icons)",
                       args.apply)
    if repo:
        branch = repo.get("default_branch") or "main"
        files = read_toolchain()
        if bootstrap(TOOLCHAIN_REPO, branch, files, args.apply):
            commit_files(TOOLCHAIN_REPO, branch, files,
                         "Add packaging toolchain", args.apply)

    if not args.toolchain_only:
        for app_id in args.app or list(APPS):
            print("=== %s ===" % app_id)
            name = repo_name(app_id)
            repo = ensure_repo(name, "%s packaged for TerraMaster TOS 7 (Docker)" % APPS[app_id]["name"], args.apply)
            if not repo:
                continue
            branch = repo.get("default_branch") or "main"
            commit_files(name, branch, app_files(app_id),
                         "Add application source and build template", args.apply)

    if not args.apply:
        print("\ndry-run only; re-run with --apply to upload")


if __name__ == "__main__":
    main()
