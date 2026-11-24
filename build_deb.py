#!/usr/bin/env python3
"""Build the CookCLI TOS 7 deb package for both architectures.

CookCLI has no official Docker Hub image, so it is packaged the deb way: the
upstream static musl binary runs as a systemd service on port 18087 and the
TOS nginx entry proxies /cookcli/ to it (external open).

Usage:
    python build_deb.py              # build and validate both architectures
    python build_deb.py --arch aarch64
    python build_deb.py --check      # validate existing packages only
"""

import argparse
import bz2
import gzip
import hashlib
import io
import json
import os
import re
import struct
import sys
import tarfile
import tempfile
import urllib.request

from build import ARCHES, DIST, ICONS, LANG_KEYS, ROOT, VERSION
from build import build_config, build_lang

APP_ID = "cookcli"
UPSTREAM_VERSION = "0.41.1"
PORT = 18087
CACHE_DIR = os.path.join(ROOT, "_scratch", "cookcli")
OUT_DIR = os.path.join(DIST, APP_ID)

RELEASE_URL = "https://github.com/cooklang/CookCLI/releases/download/v%s/" % UPSTREAM_VERSION
TARBALL = "cook-%s-linux-%%s-musl.tar.gz" % UPSTREAM_VERSION
ELF_MACHINE = {"x86_64": 62, "aarch64": 183}

DEBIAN_FILES = ("control", "preinst", "postinst", "prerm", "postrm")

SERVICE = """[Unit]
Description=CookCLI recipe server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=cookcli
Group=cookcli
Environment=TZ=Asia/Shanghai
Environment=HOME=/usr/local/cookcli/data
ExecStart=/usr/local/cookcli/bin/cookcli-server
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""

LAUNCHER = """#!/bin/sh
# Pick the recipe folder to serve: the shared folder this package creates when
# a volume is mounted, otherwise the private data directory.
APPID="cookcli"
ROOT="/usr/local/$APPID"
BASE="$ROOT/data/recipes"
for volume in /Volume*; do
    if [ -d "$volume/$APPID-data/recipes" ]; then
        BASE="$volume/$APPID-data/recipes"
        break
    fi
done
CONFIG="$ROOT/data/config"
mkdir -p "$BASE" "$CONFIG"
export COOK_CONFIG_DIR="$CONFIG"
exec "$ROOT/bin/cook" server "$BASE" \\
    --host 0.0.0.0 \\
    --port %d \\
    --url-prefix "/$APPID" \\
    --proxy-strips-prefix \\
    --max-lsp-sessions 4
""" % PORT

NGINX_CONF = """location /cookcli/ {
    proxy_pass http://127.0.0.1:%d/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;
}
""" % PORT

WEBUI_INDEX = """<!DOCTYPE html>
<html lang="zh-cn">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CookCLI</title>
<style>
  body { margin: 0; font-family: system-ui, sans-serif; background: #fff7ed; color: #7c2d12;
         display: flex; align-items: center; justify-content: center; min-height: 100vh; }
  main { max-width: 34rem; padding: 2rem; text-align: center; }
  h1 { margin: 0 0 .5rem; font-size: 1.6rem; }
  p { line-height: 1.6; margin: .5rem 0; }
  a { color: #ea580c; }
</style>
</head>
<body>
<main>
  <h1>CookCLI</h1>
  <p>食谱服务运行在 <a href="/cookcli/">/cookcli/</a>。</p>
  <p>Recipes are served at <a href="/cookcli/">/cookcli/</a>.</p>
</main>
</body>
</html>
"""

PREINST = """#!/bin/bash
# preinst - executed before the package files are unpacked
set -e

APPID="cookcli"

if ! getent group "$APPID" >/dev/null 2>&1; then
    groupadd -r "$APPID" 2>/dev/null || true
fi
if ! id -u "$APPID" >/dev/null 2>&1; then
    useradd -r -g "$APPID" -d "/usr/local/$APPID" -s /usr/sbin/nologin "$APPID" 2>/dev/null \\
        || useradd -r -d "/usr/local/$APPID" -s /bin/false "$APPID" 2>/dev/null || true
fi

mkdir -p "/usr/local/$APPID/data/config" "/usr/local/$APPID/data/recipes"
chown -R "$APPID:$APPID" "/usr/local/$APPID/data" 2>/dev/null || true

if [ "$1" = "upgrade" ]; then
    systemctl stop "$APPID.service" 2>/dev/null || true
fi

exit 0
"""

POSTINST = """#!/bin/bash
# postinst - executed after the package files have been unpacked
set -e

APPID="cookcli"
ROOT="/usr/local/$APPID"
SERVICE="$APPID.service"
SHARE="$APPID-data"

case "$1" in
    configure)
        chown -R "$APPID:$APPID" "$ROOT" 2>/dev/null || true
        chmod -R u=rwX,go=rX "$ROOT" 2>/dev/null || true
        chmod 0755 "$ROOT/bin/cook" "$ROOT/bin/cookcli-server" 2>/dev/null || true
        mkdir -p "$ROOT/data/config" "$ROOT/data/recipes"
        chown -R "$APPID:$APPID" "$ROOT/data" 2>/dev/null || true
        chmod 0750 "$ROOT/data" 2>/dev/null || true

        # Recipes are ordinary text files in a TOS shared folder, so they can be
        # managed from the File Manager or over SMB. ter_share_add is the
        # platform tool that creates the folder with the right ACL; failure is
        # not fatal because the service falls back to its private data folder.
        VOLUME="$(ls -d /Volume* 2>/dev/null | head -1)"
        SHARE_ROOT=""
        [ -n "$VOLUME" ] && SHARE_ROOT="$VOLUME/$SHARE"
        if [ ! -d "$SHARE_ROOT" ] && [ -n "$VOLUME" ] && command -v ter_share_add >/dev/null 2>&1; then
            ter_share_add -device "$(basename "$VOLUME")" -name "$SHARE" -owner "$APPID" >/dev/null 2>&1 || true
        fi
        if [ -d "$SHARE_ROOT" ]; then
            echo "recipe library: $SHARE_ROOT/recipes"
            mkdir -p "$SHARE_ROOT/recipes" 2>/dev/null || true
            chown -R "$APPID:$APPID" "$SHARE_ROOT/recipes" 2>/dev/null || true
        else
            echo "WARNING: shared folder '$SHARE' is unavailable; recipes stay in $ROOT/data/recipes"
        fi

        if [ -f "$ROOT/webui.bz2" ]; then
            mkdir -p "$ROOT/webui"
            tar -xjf "$ROOT/webui.bz2" -C "$ROOT/webui" 2>/dev/null || true
            chown -R root:root "$ROOT/webui" 2>/dev/null || true
            chmod -R a+rX "$ROOT/webui" 2>/dev/null || true
        fi
        if [ -d "$ROOT/webui" ] && [ ! -e "/usr/www/$APPID" ]; then
            ln -s "$ROOT/webui" "/usr/www/$APPID" 2>/dev/null || true
        fi

        if [ -f "$ROOT/init.d/$SERVICE" ]; then
            cp -f "$ROOT/init.d/$SERVICE" "/etc/systemd/system/$SERVICE"
            chmod 0644 "/etc/systemd/system/$SERVICE"
            systemctl daemon-reload 2>/dev/null || true
            systemctl enable "$SERVICE" 2>/dev/null || true
        fi

        if [ -n "$2" ]; then
            echo "Upgrading cookcli from version $2 to __VERSION__"
            systemctl try-restart "$SERVICE" 2>/dev/null || true
        fi
        if ! systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
            systemctl start "$SERVICE" 2>/dev/null || true
        fi
        ;;

    abort-upgrade|abort-remove|abort-deconfigure)
        ;;

    *)
        echo "postinst called with unknown argument '$1'" >&2
        exit 1
        ;;
esac

exit 0
"""

PRERM = """#!/bin/bash
# prerm - executed before the package files are removed
set -e

APPID="cookcli"

case "$1" in
    remove|deconfigure|upgrade|failed-upgrade)
        systemctl stop "$APPID.service" 2>/dev/null || true
        ;;
    *)
        ;;
esac

exit 0
"""

POSTRM = """#!/bin/bash
# postrm - executed after the package files have been removed
set -e

APPID="cookcli"

if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    systemctl disable "$APPID.service" 2>/dev/null || true
    rm -f "/etc/systemd/system/$APPID.service" 2>/dev/null || true
    systemctl daemon-reload 2>/dev/null || true
    rm -f "/usr/www/$APPID" 2>/dev/null || true
fi

# The recipe shared folder is the operator's data and is never touched here,
# not even on purge.
if [ "$1" = "purge" ]; then
    rm -rf "/usr/local/$APPID" 2>/dev/null || true
    userdel "$APPID" >/dev/null 2>&1 || true
    groupdel "$APPID" >/dev/null 2>&1 || true
fi

exit 0
"""


def log(message):
    print("[build-deb] %s" % message)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url, destination):
    """Download a URL to destination, tolerating transient failures."""
    last = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "tos-docker-apps"})
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read()
            with open(destination, "wb") as handle:
                handle.write(data)
            return
        except Exception as exc:  # network errors are retried, then reported
            last = exc
            log("download failed (attempt %d): %s" % (attempt + 1, exc))
    raise SystemExit("cannot download %s: %s" % (url, last))


def upstream_binary(arch):
    """Return the verified upstream cook binary for the architecture."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    name = TARBALL % arch
    archive = os.path.join(CACHE_DIR, name)
    checksum_file = archive + ".sha256"
    if not os.path.isfile(checksum_file):
        fetch(RELEASE_URL + name + ".sha256", checksum_file)
    expected = open(checksum_file, "r", encoding="utf-8").read().split()[0].strip().lower()
    if not os.path.isfile(archive) or sha256_file(archive) != expected:
        log("downloading %s" % name)
        fetch(RELEASE_URL + name, archive)
        actual = sha256_file(archive)
        if actual != expected:
            raise SystemExit("%s checksum mismatch: %s != %s" % (name, actual, expected))
    log("verified %s (sha256 %s)" % (name, expected[:16]))

    with tarfile.open(archive, "r:gz") as tar:
        member = tar.getmember("cook")
        return tar.extractfile(member).read()


def check_elf(binary, arch):
    if len(binary) < 20 or binary[:4] != b"\x7fELF":
        raise SystemExit("upstream cook binary is not an ELF file")
    if binary[4] != 2:
        raise SystemExit("upstream cook binary is not 64-bit")
    machine = struct.unpack("<H", binary[18:20])[0]
    if machine != ELF_MACHINE[arch]:
        raise SystemExit("upstream cook binary machine %d does not match %s" % (machine, arch))


def write_text(path, text, mode=0o644):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.chmod(path, mode)


def write_bytes(path, data, mode=0o644):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    os.chmod(path, mode)


def pack_webui(destination):
    """Pack the placeholder page the platform expects as webui.bz2."""
    payload = WEBUI_INDEX.encode("utf-8")
    info = tarfile.TarInfo("index.html")
    info.size = len(payload)
    info.mode = 0o644
    info.uid = info.gid = 0
    info.mtime = 0
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as archive:
        archive.addfile(info, io.BytesIO(payload))
    write_bytes(destination, bz2.compress(buffer.getvalue(), compresslevel=9))


def control_text(arch, installed_size):
    architecture = "amd64" if arch == "x86_64" else "arm64"
    description = (
        "Package: %s\n"
        "Version: %s\n"
        "Architecture: %s\n"
        "Section: utils\n"
        "Priority: optional\n"
        "Maintainer: TerraMaster Community Developer <dev@example.com>\n"
        "Depends: ca-certificates, systemd\n"
        "Installed-Size: %d\n"
        "Description: CookCLI - recipe server for TOS\n"
        " CookCLI turns plain-text .cook recipe files into a browsable cookbook\n"
        " with scaling, search, shopping lists and an in-browser editor. This\n"
        " package runs the upstream static binary as a systemd service behind\n"
        " the TOS nginx entry at /cookcli/.\n"
    ) % (APP_ID, VERSION, architecture, installed_size)
    return description


def measure_size(root):
    total = 0
    for base, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return max(1, total // 1024)


def assemble(arch, work_root):
    """Write the package tree for one architecture into work_root."""
    payload = os.path.join(work_root, "usr", "local", APP_ID)
    binary = upstream_binary(arch)
    check_elf(binary, arch)

    write_bytes(os.path.join(payload, "bin", "cook"), binary, 0o755)
    write_text(os.path.join(payload, "bin", "cookcli-server"), LAUNCHER, 0o755)
    write_text(os.path.join(payload, "init.d", "%s.service" % APP_ID), SERVICE)
    write_text(os.path.join(payload, "nginx", "%s.conf" % APP_ID), NGINX_CONF)
    write_text(os.path.join(payload, "%s.lang" % APP_ID), build_lang(APP_ID))
    write_text(os.path.join(payload, "images", "icons", "%s.svg" % APP_ID), ICONS[APP_ID])
    with open(os.path.join(payload, "config.ini"), "w", encoding="utf-8", newline="\n") as handle:
        json.dump(build_config(APP_ID, arch), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    pack_webui(os.path.join(payload, "webui.bz2"))

    debian = os.path.join(work_root, "DEBIAN")
    for name, text in (
        ("preinst", PREINST),
        ("postinst", POSTINST.replace("__VERSION__", VERSION)),
        ("prerm", PRERM),
        ("postrm", POSTRM),
    ):
        write_text(os.path.join(debian, name), text, 0o755)
    write_text(os.path.join(debian, "control"), control_text(arch, measure_size(payload)))
    return work_root


def _tar_bytes(source_root, skip_debian=False):
    """Deterministic tar.gz of a tree, using ./ prefixed entries like dpkg."""
    entries = []

    def walk(base):
        relative = os.path.relpath(base, source_root)
        if relative == ".":
            relative = ""
        names = sorted(os.listdir(base))
        dirs = [name for name in names if os.path.isdir(os.path.join(base, name))]
        files = [name for name in names if not os.path.isdir(os.path.join(base, name))]
        if skip_debian and base == source_root:
            dirs = [name for name in dirs if name != "DEBIAN"]
        for name in dirs:
            path = os.path.join(base, name)
            arcname = "%s/%s" % (relative, name) if relative else name
            entries.append((path, arcname, True))
            walk(path)
        for name in files:
            path = os.path.join(base, name)
            arcname = "%s/%s" % (relative, name) if relative else name
            entries.append((path, arcname, False))

    walk(source_root)

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as archive:
        root_info = tarfile.TarInfo("./")
        root_info.type = tarfile.DIRTYPE
        root_info.mode = 0o755
        root_info.uid = root_info.gid = 0
        root_info.uname = root_info.gname = "root"
        archive.addfile(root_info)
        for path, arcname, is_dir in entries:
            info = archive.gettarinfo(path, arcname="./" + arcname)
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = 0
            if is_dir:
                info.mode = 0o755
                info.size = 0
                archive.addfile(info)
            else:
                base = arcname.rsplit("/", 1)[-1]
                executable = base in ("preinst", "postinst", "prerm", "postrm", "cook", "cookcli-server")
                info.mode = 0o755 if executable else 0o644
                with open(path, "rb") as handle:
                    archive.addfile(info, handle)
    return gzip.compress(buffer.getvalue(), compresslevel=9, mtime=0)


def _ar_entry(name, payload):
    header = "%-16s%-12d%-6d%-6d%-8s%-10d`\n" % (name, 0, 0, 0, "100644", len(payload))
    out = header.encode("ascii") + payload
    if len(payload) % 2:
        out += b"\n"
    return out


def write_deb(work_root, output):
    control_tar = _tar_bytes(os.path.join(work_root, "DEBIAN"))
    data_tar = _tar_bytes(work_root, skip_debian=True)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "wb") as handle:
        handle.write(b"!<arch>\n")
        handle.write(_ar_entry("debian-binary", b"2.0\n"))
        handle.write(_ar_entry("control.tar.gz", control_tar))
        handle.write(_ar_entry("data.tar.gz", data_tar))
    digest = sha256_file(output)
    with open(output + ".sha256", "w", encoding="utf-8", newline="\n") as handle:
        handle.write("%s  %s\n" % (digest, os.path.basename(output)))
    log("built %s (%d bytes, sha256 %s)" % (
        os.path.relpath(output, ROOT), os.path.getsize(output), digest[:16]))
    return digest


def read_ar(path):
    """Return {member name: bytes} for an ar archive."""
    with open(path, "rb") as handle:
        data = handle.read()
    if not data.startswith(b"!<arch>\n"):
        raise SystemExit("%s is not an ar archive" % path)
    members = {}
    offset = 8
    while offset + 60 <= len(data):
        header = data[offset:offset + 60]
        name = header[:16].decode("ascii").strip()
        size = int(header[48:58].decode("ascii").strip())
        start = offset + 60
        members[name] = data[start:start + size]
        offset = start + size + (size % 2)
    return members


def validate(arch):
    """Open the produced deb and check the files the platform parser reads."""
    errors = []
    path = os.path.join(OUT_DIR, "%s_%s.deb" % (APP_ID, arch))
    if not os.path.isfile(path):
        return ["missing %s" % path]
    try:
        members = read_ar(path)
        if members.get("debian-binary") != b"2.0\n":
            errors.append("debian-binary member is wrong")
        control = tarfile.open(fileobj=io.BytesIO(gzip.decompress(members["control.tar.gz"])), mode="r:")
        control_text_ = control.extractfile("./control").read().decode("utf-8")
        data = tarfile.open(fileobj=io.BytesIO(gzip.decompress(members["data.tar.gz"])), mode="r:")
    except KeyError as exc:
        return ["%s: missing archive member %s" % (arch, exc)]

    if "Package: %s" % APP_ID not in control_text_:
        errors.append("control Package mismatch")
    if "Version: %s" % VERSION not in control_text_:
        errors.append("control Version mismatch")
    expected_arch = "amd64" if arch == "x86_64" else "arm64"
    if "Architecture: %s" % expected_arch not in control_text_:
        errors.append("control Architecture mismatch")

    payload = "usr/local/%s/" % APP_ID
    required = [
        "config.ini", "%s.lang" % APP_ID, "images/icons/%s.svg" % APP_ID, "webui.bz2",
        "nginx/%s.conf" % APP_ID, "init.d/%s.service" % APP_ID,
        "bin/cook", "bin/cookcli-server",
    ]
    names = set(data.getnames())
    for item in required:
        if "./" + payload + item not in names:
            errors.append("data.tar missing %s" % (payload + item))

    try:
        config = json.loads(data.extractfile("./" + payload + "config.ini").read().decode("utf-8"))
        if config.get("id") != APP_ID:
            errors.append("config.ini id mismatch")
        if config.get("platform") != arch:
            errors.append("config.ini platform mismatch")
        if config.get("application_type") != "deb":
            errors.append("config.ini application_type must be deb")
        if config.get("type") != "iframe":
            errors.append("config.ini type must be iframe")
        if config.get("open_path") is not None:
            errors.append("config.ini must not set open_path in iframe mode")
        if config.get("path") != "/%s/" % APP_ID:
            errors.append("config.ini path must be /%s/" % APP_ID)
        if config.get("package") != APP_ID or config.get("system_id") != APP_ID:
            errors.append("config.ini package/system_id mismatch")
    except KeyError:
        errors.append("config.ini could not be read")

    if errors:
        return errors

    lang = data.extractfile("./" + payload + "%s.lang" % APP_ID).read().decode("utf-8")
    for key in LANG_KEYS:
        if "[%s]" % key not in lang:
            errors.append("lang missing %s" % key)
            continue
        block = lang.split("[%s]" % key, 1)[1].split("\n[", 1)[0]
        for field in ("name", "auth", "descript"):
            match = re.search(r'^%s = "(.*)"$' % field, block, re.M)
            if not match or not match.group(1).strip():
                errors.append("%s: %s empty" % (key, field))

    svg = data.extractfile("./" + payload + "images/icons/%s.svg" % APP_ID).read().decode("utf-8")
    if "<svg" not in svg or "viewBox" not in svg:
        errors.append("svg missing svg/viewBox")

    conf = data.extractfile("./" + payload + "nginx/%s.conf" % APP_ID).read().decode("utf-8")
    if "location /%s/" % APP_ID not in conf or "proxy_pass http://127.0.0.1:%d/" % PORT not in conf:
        errors.append("nginx config does not proxy /%s/ to %d" % (APP_ID, PORT))
    if "server {" in conf:
        errors.append("nginx config must not define a server block")

    service = data.extractfile("./" + payload + "init.d/%s.service" % APP_ID).read().decode("utf-8")
    if "ExecStart=/usr/local/%s/bin/cookcli-server" % APP_ID not in service:
        errors.append("service unit ExecStart mismatch")

    webui = tarfile.open(fileobj=io.BytesIO(bz2_decompress(
        data.extractfile("./" + payload + "webui.bz2").read())), mode="r:")
    if "index.html" not in webui.getnames():
        errors.append("webui.bz2 does not contain index.html")

    return errors


def bz2_decompress(payload):
    import bz2

    return bz2.decompress(payload)


def build(arch):
    work_root = tempfile.mkdtemp(prefix="cookcli-deb-")
    assemble(arch, work_root)
    output = os.path.join(OUT_DIR, "%s_%s.deb" % (APP_ID, arch))
    return write_deb(work_root, output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--arch", choices=ARCHES, action="append")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    arches = args.arch or ARCHES
    if not args.check:
        for arch in arches:
            build(arch)

    errors = []
    for arch in arches:
        errors.extend(validate(arch))
    if errors:
        print("\nVALIDATION FAILED")
        for item in errors:
            print(" -", item)
        sys.exit(1)
    print("\nvalidation: %d deb package(s) OK" % len(arches))


if __name__ == "__main__":
    main()
