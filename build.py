#!/usr/bin/env python3
"""Build TOS 7 Docker application packages for the seven apps in this repo.

Each package is a .tar.gz whose root holds exactly:
    config.ini, <appid>.lang, <appid>.svg, docker-compose.yml

Usage:
    python build.py                # build both architectures
    python build.py --arch x86_64
    python build.py --check        # validate existing dist without rebuilding
"""

import argparse
import base64
import gzip
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import tarfile
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
SECRETS_FILE = os.path.join(ROOT, ".secrets.json")

VERSION = "1.0.0"
PUBLISHER = "TerraMaster Community Developer"
PUBLISHER_ZH = "TerraMaster 社区开发者"
LOW_VERSION = "7.0"
CATEGORY = ["Utilities"]
ARCHES = ["x86_64", "aarch64"]

LANG_KEYS = [
    "zh-cn", "zh-hk", "en-us", "fr-fr", "de-de", "it-it", "es-es",
    "hu-hu", "ja-jp", "ko-kr", "pl-pl", "ru-ru", "tr-tr", "pt-pt",
]

# ---------------------------------------------------------------------------
# Icons: transparent background, 96x96 viewBox, no official artwork.
# ---------------------------------------------------------------------------

ICONS = {
    "fileflows": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="96" height="96">
  <circle cx="48" cy="48" r="40" fill="#2563eb"/>
  <path d="M40 31l24 17-24 17z" fill="#ffffff"/>
  <path d="M21 25h15M21 71h15" stroke="#bfdbfe" stroke-width="5" stroke-linecap="round"/>
</svg>
""",
    "lychee": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="96" height="96">
  <circle cx="48" cy="48" r="40" fill="#e11d48"/>
  <rect x="24" y="30" width="48" height="36" rx="5" fill="#ffffff"/>
  <circle cx="37" cy="42" r="4" fill="#e11d48"/>
  <path d="M28 60l12-12 8 8 6-6 14 14z" fill="#fb7185"/>
</svg>
""",
    "coder-code-server": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="96" height="96">
  <circle cx="48" cy="48" r="40" fill="#0ea5e9"/>
  <path d="M36 33L23 48l13 15M60 33l13 15-13 15" fill="none" stroke="#ffffff" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M54 29L42 67" stroke="#e0f2fe" stroke-width="6" stroke-linecap="round"/>
</svg>
""",
    "bookstack": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="96" height="96">
  <rect x="22" y="20" width="52" height="14" rx="3" fill="#f59e0b"/>
  <rect x="18" y="38" width="60" height="14" rx="3" fill="#f97316"/>
  <rect x="26" y="56" width="44" height="18" rx="3" fill="#dc2626"/>
  <path d="M30 27h20M26 45h28M34 66h18" stroke="#ffffff" stroke-width="3" stroke-linecap="round"/>
</svg>
""",
    "stirling-pdf": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="96" height="96">
  <path d="M27 13h28l17 17v49a4 4 0 0 1-4 4H27a4 4 0 0 1-4-4V17a4 4 0 0 1 4-4z" fill="#ffffff" stroke="#dc2626" stroke-width="4" stroke-linejoin="round"/>
  <path d="M55 13v17h17" fill="#fecaca"/>
  <text x="47" y="64" font-family="Arial,Helvetica,sans-serif" font-size="17" font-weight="700" fill="#dc2626" text-anchor="middle">PDF</text>
</svg>
""",
    "appflowy": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="96" height="96">
  <rect x="16" y="14" width="28" height="20" rx="4" fill="#6366f1"/>
  <rect x="52" y="38" width="28" height="20" rx="4" fill="#818cf8"/>
  <rect x="16" y="62" width="28" height="20" rx="4" fill="#a5b4fc"/>
  <path d="M44 24h4a4 4 0 0 1 4 4v10M44 72h4a4 4 0 0 0 4-4V58" fill="none" stroke="#6366f1" stroke-width="4" stroke-linecap="round"/>
</svg>
""",
    "dozzle": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="96" height="96">
  <circle cx="48" cy="48" r="40" fill="#0f172a"/>
  <path d="M27 33l13 10-13 10" fill="none" stroke="#34d399" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M48 55h22M27 71h44" stroke="#64748b" stroke-width="6" stroke-linecap="round"/>
  <path d="M48 55h22" stroke="#34d399" stroke-width="6" stroke-linecap="round"/>
</svg>
""",
}

# ---------------------------------------------------------------------------
# Application definitions
# ---------------------------------------------------------------------------

APPS = {}

APPS["fileflows"] = {
    "name": "FileFlows",
    "help": "https://fileflows.com/docs",
    "official": "https://fileflows.com",
    "compose": """version: "3.8"
services:
  fileflows:
    image: revenz/fileflows:26.11
    container_name: fileflows
    restart: unless-stopped
    ports:
      - "19200:5000"
    volumes:
      - ./data/data:/app/Data
      - ./data/logs:/app/Logs
      - ./data/temp:/app/temp
    environment:
      - TZ=Asia/Shanghai
      - PUID=1000
      - PGID=1000
    security_opt:
      - no-new-privileges:true

x-app-meta:
  web:
    port: 19200
    protocol: http
""",
    "descript": {
        "zh-cn": "自动化的媒体文件处理流水线。按自定义规则对视频和音频转码、重封装、补充或替换音轨、提取字幕并整理媒体库，处理流程与任务队列通过浏览器管理。",
        "zh-hk": "自動化的媒體檔案處理流水線。按自訂規則對影片和音訊轉碼、重新封裝、補充或替換音軌、擷取字幕並整理媒體庫，處理流程與任務佇列可透過瀏覽器管理。",
        "en-us": "An automated media processing pipeline. Transcode, remux, add or replace audio tracks, extract subtitles and organize your library with custom rules, managed from a browser.",
    },
    "important": {
        "zh-cn": "数据保存在应用数据目录的 data、logs 与 temp 子目录中，卸载时只有勾选删除数据才会清理。",
        "zh-hk": "資料保存在應用資料目錄的 data、logs 與 temp 子目錄中，解除安裝時只有勾選刪除資料才會清理。",
        "en-us": "Data is kept under the application data directory in the data, logs and temp subfolders; uninstalling only removes it when delete-data is selected.",
    },
    "release_note": "1.0.0: First release, packaged from the official Docker Hub image revenz/fileflows with persistent data, logs and temp folders.",
}

APPS["lychee"] = {
    "name": "Lychee",
    "help": "https://lycheeorg.github.io/docs/",
    "official": "https://lycheeorg.github.io/",
    "compose": """version: "3.8"
services:
  lychee:
    image: lycheeorg/lychee:v7.13.1
    container_name: lychee
    restart: unless-stopped
    ports:
      - "18081:80"
    volumes:
      - ./data/conf:/conf
      - ./data/uploads:/uploads
      - ./data/sym:/sym
    environment:
      - TZ=Asia/Shanghai
      - TIMEZONE=Asia/Shanghai
      - PHP_TZ=Asia/Shanghai
      - PUID=1000
      - PGID=1000
      - DB_CONNECTION=sqlite

x-app-meta:
  web:
    port: 18081
    protocol: http
""",
    "descript": {
        "zh-cn": "自托管的照片管理库。上传与整理照片、相册和标签、搜索与分享链接，支持 RAW 和视频；使用内置 SQLite 数据库，无需额外的数据库服务。",
        "zh-hk": "自託管的相片管理庫。上傳與整理相片、相簿和標籤、搜尋與分享連結，支援 RAW 和影片；使用內建 SQLite 資料庫，無需額外的資料庫服務。",
        "en-us": "A self-hosted photo library. Upload and organize photos, albums and tags, search and share links, with RAW and video support and a built-in SQLite database.",
    },
    "important": {
        "zh-cn": "首次打开网页时在浏览器中创建管理员账号。照片、数据库与配置保存在应用数据目录中。",
        "zh-hk": "首次開啟網頁時在瀏覽器中建立管理員帳號。相片、資料庫與設定保存在應用資料目錄中。",
        "en-us": "Create the administrator account in the browser on first visit. Photos, database and configuration are stored in the application data directory.",
    },
    "release_note": "1.0.0: First release, packaged from the official Docker Hub image lycheeorg/lychee with built-in SQLite storage.",
}

APPS["coder-code-server"] = {
    "name": "code-server",
    "help": "https://coder.com/docs/code-server",
    "official": "https://coder.com/",
    "compose": """version: "3.8"
services:
  coder-code-server:
    image: codercom/code-server:4.146.0
    container_name: coder-code-server
    restart: unless-stopped
    user: "1000:1000"
    ports:
      - "18082:8080"
    volumes:
      - ./data:/home/coder
    environment:
      - TZ=Asia/Shanghai
      - DOCKER_USER=coder
    security_opt:
      - no-new-privileges:true
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:8080/healthz || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s

x-app-meta:
  web:
    port: 18082
    protocol: http
""",
    "descript": {
        "zh-cn": "在浏览器中使用 VS Code 的远程开发环境。打开 NAS 上的目录进行编辑，使用终端与扩展，工作区与配置保存在应用数据目录。",
        "zh-hk": "在瀏覽器中使用 VS Code 的遠端開發環境。開啟 NAS 上的目錄進行編輯，使用終端與擴充功能，工作區與設定保存在應用資料目錄。",
        "en-us": "Run VS Code in the browser. Open folders on the NAS, use the terminal and extensions, with workspace and settings kept in the application data directory.",
    },
    "important": {
        "zh-cn": "首次启动会自动生成随机登录密码，保存在容器内 /home/coder/.config/code-server/config.yaml；可在容器终端查看，登录后也可在设置中修改。",
        "zh-hk": "首次啟動會自動產生隨機登入密碼，保存在容器內 /home/coder/.config/code-server/config.yaml；可在容器終端查看，登入後也可在設定中修改。",
        "en-us": "A random login password is generated on first start and stored in /home/coder/.config/code-server/config.yaml inside the container; view it from the container terminal.",
    },
    "release_note": "1.0.0: First release, packaged from the official Docker Hub image codercom/code-server, running as user 1000.",
}

APPS["bookstack"] = {
    "name": "BookStack",
    "help": "https://www.bookstackapp.com/docs/",
    "official": "https://www.bookstackapp.com/",
    "compose": """version: "3.8"
services:
  bookstack-db:
    image: mariadb:10.11
    container_name: bookstack-db
    restart: unless-stopped
    volumes:
      - ./data/db:/var/lib/mysql
    environment:
      - TZ=Asia/Shanghai
      - MARIADB_ROOT_PASSWORD=@@db_root@@
      - MARIADB_DATABASE=bookstack
      - MARIADB_USER=bookstack
      - MARIADB_PASSWORD=@@db_password@@
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 30s

  bookstack:
    image: linuxserver/bookstack:26.09.3
    container_name: bookstack
    restart: unless-stopped
    depends_on:
      bookstack-db:
        condition: service_healthy
    ports:
      - "18083:80"
    volumes:
      - ./data/app:/config
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Asia/Shanghai
      - APP_KEY=@@app_key@@
      - DB_HOST=bookstack-db
      - DB_PORT=3306
      - DB_DATABASE=bookstack
      - DB_USERNAME=bookstack
      - DB_PASSWORD=@@db_password@@
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:80/login >/dev/null || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 180s

x-app-meta:
  web:
    port: 18083
    protocol: http
""",
    "descript": {
        "zh-cn": "按书籍、章节和页面组织的知识库与文档系统。提供所见即所得编辑器、图片与附件、全文搜索、用户与权限管理，数据库随应用一并部署。",
        "zh-hk": "按書籍、章節和頁面組織的知識庫與文件系統。提供所見即所得的編輯器、圖片與附件、全文搜尋、使用者與權限管理，資料庫隨應用一併部署。",
        "en-us": "A knowledge base organized by books, chapters and pages, with a WYSIWYG editor, images and attachments, full-text search and user permissions, backed by a bundled MariaDB.",
    },
    "important": {
        "zh-cn": "初始管理员账号为 admin@admin.com，密码 password，首次登录后请立即修改。若通过 NAS 地址访问，请把应用配置中的 APP_URL 设置为实际访问地址（如 http://192.168.1.10:18083）并重启容器。数据库密码在打包时随机生成并写入应用配置。",
        "zh-hk": "初始管理員帳號為 admin@admin.com，密碼 password，首次登入後請立即修改。若透過 NAS 位址存取，請把應用設定中的 APP_URL 設定為實際存取位址（如 http://192.168.1.10:18083）並重新啟動容器。資料庫密碼在打包時隨機產生並寫入應用設定。",
        "en-us": "The initial administrator is admin@admin.com with password password; change it after the first login. If you access BookStack through the NAS address, set APP_URL in the application configuration to the real address (for example http://192.168.1.10:18083) and restart the container. The database password is randomly generated when the package is built.",
    },
    "release_note": "1.0.0: First release, packaged from linuxserver/bookstack with a bundled MariaDB database and persistent configuration.",
    "secrets": {
        "db_root": "bookstack_root_",
        "db_password": "bookstack_db_",
        "app_key": "app_key",
    },
}

APPS["stirling-pdf"] = {
    "name": "Stirling-PDF",
    "help": "https://docs.stirlingpdf.com/",
    "official": "https://www.stirlingpdf.com/",
    "compose": """version: "3.8"
services:
  stirling-pdf:
    image: stirlingtools/stirling-pdf:3.5.0
    container_name: stirling-pdf
    restart: unless-stopped
    ports:
      - "18084:8080"
    volumes:
      - ./data/configs:/configs
      - ./data/logs:/logs
      - ./data/customFiles:/customFiles
      - ./data/pipeline:/pipeline
      - ./data/storage:/storage
    environment:
      - TZ=Asia/Shanghai
      - PUID=1000
      - PGID=1000
      - SYSTEM_DEFAULTLOCALE=zh-CN
      - SECURITY_ENABLELOGIN=false
      - DOCKER_ENABLE_SECURITY=false
    security_opt:
      - no-new-privileges:true
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8080/api/v1/info/status | grep -q UP"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 60s

x-app-meta:
  web:
    port: 18084
    protocol: http
""",
    "descript": {
        "zh-cn": "本地运行的 PDF 工具箱：合并、拆分、压缩、格式转换、OCR、加密与水印等五十多种操作，文件只在 NAS 上处理，不上传到外部服务。",
        "zh-hk": "本機執行的 PDF 工具箱：合併、拆分、壓縮、格式轉換、OCR、加密與浮水印等五十多種操作，檔案只在 NAS 上處理，不上傳到外部服務。",
        "en-us": "A locally hosted PDF toolbox with more than fifty operations such as merge, split, compress, convert, OCR, encryption and watermarking; files are processed on the NAS only.",
    },
    "important": {
        "zh-cn": "默认不启用登录认证；如需访问控制，请在应用配置中把 SECURITY_ENABLELOGIN 改为 true。配置、日志与临时文件保存在应用数据目录。",
        "zh-hk": "預設不啟用登入驗證；如需存取控制，請在應用設定中把 SECURITY_ENABLELOGIN 改為 true。設定、日誌與暫存檔案保存在應用資料目錄。",
        "en-us": "Login is disabled by default; set SECURITY_ENABLELOGIN to true in the application configuration if you need access control. Configs, logs and temporary files stay in the application data directory.",
    },
    "release_note": "1.0.0: First release, packaged from the official Docker Hub image stirlingtools/stirling-pdf, running with UID/GID 1000.",
}

APPS["dozzle"] = {
    "name": "Dozzle",
    "help": "https://dozzle.dev/",
    "official": "https://dozzle.dev/",
    "compose": """version: "3.8"
services:
  dozzle:
    image: amir20/dozzle:latest
    container_name: dozzle
    restart: unless-stopped
    ports:
      - "18086:8080"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./data:/data
    environment:
      - TZ=Asia/Shanghai
      - DOZZLE_LEVEL=info
    security_opt:
      - no-new-privileges:true

x-app-meta:
  web:
    port: 18086
    protocol: http
""",
    "descript": {
        "zh-cn": "实时查看 Docker 容器日志的轻量 Web 面板，支持搜索、日志分流和多容器聚合，便于排查应用运行问题。",
        "zh-hk": "即時查看 Docker 容器日誌的輕量 Web 面板，支援搜尋、日誌分流和多容器彙總，便於排查應用執行問題。",
        "en-us": "A lightweight realtime Docker log viewer with search, streaming and multi-container aggregation for troubleshooting running applications.",
    },
    "important": {
        "zh-cn": "需要只读访问 Docker 套接字，权限较高，仅建议在可信网络中使用。",
        "zh-hk": "需要唯讀存取 Docker 套接字，權限較高，僅建議在可信網路中使用。",
        "en-us": "Requires read-only access to the Docker socket, which is a high privilege; use it only on a trusted network.",
    },
    "release_note": "1.0.0: First release, packaged from the official Docker Hub image amir20/dozzle with a read-only Docker socket mount.",
}

APPS["appflowy"] = {
    "name": "AppFlowy",
    "help": "https://appflowy.com/docs",
    "official": "https://appflowy.com/",
    "compose": """version: "3.8"
services:
  appflowy-db:
    image: pgvector/pgvector:pg16
    container_name: appflowy-db
    restart: unless-stopped
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
    environment:
      - TZ=Asia/Shanghai
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=@@pg_password@@
      - POSTGRES_DB=postgres
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d postgres"]
      interval: 10s
      timeout: 5s
      retries: 10

  appflowy-redis:
    image: redis:7-alpine
    container_name: appflowy-redis
    restart: unless-stopped
    volumes:
      - ./data/redis:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 10

  appflowy-minio:
    image: elestio/minio:latest
    container_name: appflowy-minio
    restart: unless-stopped
    command: server /data --console-address ":9001"
    volumes:
      - ./data/minio:/data
    environment:
      - MINIO_ROOT_USER=@@s3_key@@
      - MINIO_ROOT_PASSWORD=@@s3_secret@@
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:9000/minio/health/live || exit 1"]
      interval: 30s
      timeout: 20s
      retries: 3

  appflowy-gotrue:
    image: appflowyinc/gotrue:latest
    container_name: appflowy-gotrue
    restart: unless-stopped
    depends_on:
      appflowy-db:
        condition: service_healthy
    environment:
      - GOTRUE_ADMIN_EMAIL=admin@example.com
      - GOTRUE_ADMIN_PASSWORD=@@admin_password@@
      - GOTRUE_DISABLE_SIGNUP=false
      - GOTRUE_SITE_URL=appflowy-flutter://
      - GOTRUE_URI_ALLOW_LIST=**
      - GOTRUE_JWT_SECRET=@@jwt_secret@@
      - GOTRUE_JWT_EXP=3600
      - GOTRUE_JWT_ADMIN_GROUP_NAME=supabase_admin
      - GOTRUE_DB_DRIVER=postgres
      - API_EXTERNAL_URL=http://localhost:18085/gotrue
      - DATABASE_URL=postgres://postgres:@@pg_password@@@appflowy-db:5432/postgres?search_path=auth
      - PORT=9999
      - GOTRUE_MAILER_AUTOCONFIRM=true
    healthcheck:
      test: ["CMD-SHELL", "curl --fail http://127.0.0.1:9999/health || exit 1"]
      interval: 5s
      timeout: 5s
      retries: 12
      start_period: 40s

  appflowy-cloud:
    image: appflowyinc/appflowy_cloud:latest
    container_name: appflowy-cloud
    restart: unless-stopped
    depends_on:
      appflowy-gotrue:
        condition: service_healthy
      appflowy-redis:
        condition: service_healthy
      appflowy-minio:
        condition: service_healthy
    environment:
      - RUST_LOG=info
      - APPFLOWY_ENVIRONMENT=production
      - APPFLOWY_DATABASE_URL=postgres://postgres:@@pg_password@@@appflowy-db:5432/postgres
      - APPFLOWY_REDIS_URI=redis://appflowy-redis:6379
      - APPFLOWY_GOTRUE_JWT_SECRET=@@jwt_secret@@
      - APPFLOWY_GOTRUE_BASE_URL=http://appflowy-gotrue:9999
      - APPFLOWY_S3_CREATE_BUCKET=true
      - APPFLOWY_S3_USE_MINIO=true
      - APPFLOWY_S3_MINIO_URL=http://appflowy-minio:9000
      - APPFLOWY_S3_ACCESS_KEY=@@s3_key@@
      - APPFLOWY_S3_SECRET_KEY=@@s3_secret@@
      - APPFLOWY_S3_BUCKET=appflowy
      - APPFLOWY_S3_REGION=us-east-1
      - APPFLOWY_S3_PRESIGNED_URL_ENDPOINT=http://localhost:18085/minio-api
      - APPFLOWY_ACCESS_CONTROL=true
      - APPFLOWY_BASE_URL=http://localhost:18085
      - APPFLOWY_WEB_URL=http://localhost:18085
      - AI_ENABLED=false
    healthcheck:
      test: ["CMD-SHELL", "curl --fail http://127.0.0.1:8000/api/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 12

  appflowy-web:
    image: appflowyinc/appflowy_web:latest
    container_name: appflowy-web
    restart: unless-stopped
    depends_on:
      appflowy-cloud:
        condition: service_healthy
    environment:
      - APPFLOWY_BASE_URL=http://localhost:18085
      - APPFLOWY_GOTRUE_BASE_URL=http://localhost:18085/gotrue
      - APPFLOWY_WS_BASE_URL=ws://localhost:18085/ws/v2

  appflowy-gateway:
    image: nginxinc/nginx-unprivileged:alpine
    container_name: appflowy-gateway
    restart: unless-stopped
    depends_on:
      - appflowy-web
      - appflowy-cloud
      - appflowy-gotrue
    ports:
      - "18085:8080"
    command:
      - /bin/sh
      - -c
      - |
        cat > /tmp/gateway.conf <<'EOF'
        worker_processes 1;
        events { worker_connections 1024; }
        http {
          include /etc/nginx/mime.types;
          client_max_body_size 100m;
          server {
            listen 8080;
            location /api { proxy_pass http://appflowy-cloud:8000; }
            location /ws {
              proxy_pass http://appflowy-cloud:8000;
              proxy_http_version 1.1;
              proxy_set_header Upgrade $$http_upgrade;
              proxy_set_header Connection "upgrade";
            }
            location /gotrue/ { proxy_pass http://appflowy-gotrue:9999/; }
            location /minio-api/ { proxy_pass http://appflowy-minio:9000/; }
            location / { proxy_pass http://appflowy-web:80; }
          }
        }
        EOF
        nginx -c /tmp/gateway.conf -g 'daemon off;'

x-app-meta:
  web:
    port: 18085
    protocol: http
""",
    "descript": {
        "zh-cn": "自托管的 AppFlowy 协作工作区，包含账号认证、数据库、对象存储、实时协作后端与 Web 前端。注意：默认访问地址为 localhost，安装后需要按实际 NAS 地址修改应用配置。",
        "zh-hk": "自託管的 AppFlowy 協作工作區，包含帳號驗證、資料庫、物件儲存、即時協作後端與 Web 前端。注意：預設存取位址為 localhost，安裝後需要按實際 NAS 位址修改應用設定。",
        "en-us": "A self-hosted AppFlowy workspace with authentication, database, object storage, realtime collaboration backend and web frontend. Note: the base URL defaults to localhost and must be changed to the NAS address after installation.",
    },
    "important": {
        "zh-cn": "高风险：APPFLOWY_BASE_URL 目前写死为 http://localhost:18085。安装后必须在应用 compose 中改成 NAS 的实际地址并重建容器，否则网页端无法连接后端。默认管理员为 admin@example.com，密码随机生成。",
        "zh-hk": "高風險：APPFLOWY_BASE_URL 目前寫死為 http://localhost:18085。安裝後必須在應用 compose 中改成 NAS 的實際位址並重建容器，否則網頁端無法連線後端。預設管理員為 admin@example.com，密碼隨機產生。",
        "en-us": "High risk: APPFLOWY_BASE_URL is fixed to http://localhost:18085. After installation you must replace it with the NAS address in the application compose file and recreate the containers. The default administrator is admin@example.com with a randomly generated password.",
    },
    "release_note": "1.0.0: First release of the self-hosted AppFlowy stack. The base URL must be edited after installation; MinIO is provided by a community Docker Hub image.",
    "secrets": {
        "pg_password": "af_pg_",
        "jwt_secret": "af_jwt_",
        "s3_key": "af_s3key_",
        "s3_secret": "af_s3secret_",
        "admin_password": "af_admin_",
    },
}

PUBLISHER_BY_LANG = {
    "zh-cn": PUBLISHER_ZH,
    "zh-hk": "TerraMaster 社群開發者",
}
EN_FALLBACK = {
    "fr-fr": "Développeur communautaire TerraMaster",
    "de-de": "TerraMaster Community-Entwickler",
    "it-it": "Sviluppatore della community TerraMaster",
    "es-es": "Desarrollador de la comunidad TerraMaster",
    "hu-hu": "TerraMaster közösségi fejlesztő",
    "ja-jp": "TerraMaster コミュニティ開発者",
    "ko-kr": "TerraMaster 커뮤니티 개발자",
    "pl-pl": "Społecznościowy deweloper TerraMaster",
    "ru-ru": "Разработчик сообщества TerraMaster",
    "tr-tr": "TerraMaster topluluk geliştiricisi",
    "pt-pt": "Programador da comunidade TerraMaster",
}


def load_secrets():
    if os.path.exists(SECRETS_FILE):
        with open(SECRETS_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    data = {}
    for app_id, app in APPS.items():
        for key in app.get("secrets", {}):
            if key == "app_key":
                data.setdefault(app_id, {})[key] = base64.b64encode(secrets.token_bytes(32)).decode()
            elif key == "jwt_secret":
                data.setdefault(app_id, {})[key] = secrets.token_urlsafe(40)
            elif key == "admin_password":
                data.setdefault(app_id, {})[key] = "Af-" + secrets.token_urlsafe(12)
            elif key == "s3_key":
                data.setdefault(app_id, {})[key] = "af" + secrets.token_hex(8)
            else:
                data.setdefault(app_id, {})[key] = secrets.token_urlsafe(18)
    with open(SECRETS_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    return data


def render_compose(app_id, secrets_map):
    text = APPS[app_id]["compose"]
    for key, value in secrets_map.get(app_id, {}).items():
        text = text.replace("@@%s@@" % key, value)
    leftovers = re.findall(r"@@[a-z_]+@@", text)
    if leftovers:
        raise SystemExit("unresolved placeholders in %s: %s" % (app_id, sorted(set(leftovers))))
    return text


def build_config(app_id, arch):
    app = APPS[app_id]
    return {
        "id": app_id,
        "icon": "/images/icons/%s.svg" % app_id,
        "publisher": PUBLISHER,
        "exec": True,
        "open_path": True,
        "help": app["help"],
        "version": VERSION,
        "recommend": False,
        "beta": False,
        "low_version": LOW_VERSION,
        "category": CATEGORY,
        "depend": ["DockerEngine"],
        "relation": ["docker", "DockerEngine"],
        "platform": arch,
        "official": app["official"],
        "application_type": "docker",
        "compose_project": app_id,
        "user": app_id,
        "all_user_display": True,
        "allow_open_in_mobile": False,
    }


def build_lang(app_id):
    app = APPS[app_id]
    lines = []
    for lang in LANG_KEYS:
        if lang in ("zh-cn", "zh-hk"):
            descript = app["descript"][lang]
            important = app["important"][lang]
            auth = PUBLISHER_BY_LANG[lang]
            release = app["release_note"]
        else:
            descript = app["descript"]["en-us"]
            important = app["important"]["en-us"]
            auth = PUBLISHER_BY_LANG.get(lang, EN_FALLBACK.get(lang, PUBLISHER))
            release = app["release_note"]
        lines.append("[%s]" % lang)
        lines.append('name = "%s"' % app["name"])
        lines.append('auth = "%s"' % auth)
        lines.append('descript = "%s"' % descript)
        lines.append('release_note = "%s"' % release)
        lines.append('important = "%s"' % important)
        lines.append("")
    return "\n".join(lines)


def normalize_lf(path):
    with open(path, "rb") as fh:
        data = fh.read()
    data = data.replace(b"\r\n", b"\n")
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    with open(path, "wb") as fh:
        fh.write(data)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_one(app_id, arch, secrets_map):
    work = os.path.join(ROOT, "build", "%s_%s" % (app_id, arch))
    if os.path.isdir(work):
        shutil.rmtree(work)
    os.makedirs(work)

    config_path = os.path.join(work, "config.ini")
    with open(config_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(build_config(app_id, arch), fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    with open(os.path.join(work, "%s.lang" % app_id), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(build_lang(app_id))

    with open(os.path.join(work, "%s.svg" % app_id), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(ICONS[app_id])

    with open(os.path.join(work, "docker-compose.yml"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_compose(app_id, secrets_map))

    for name in ("config.ini", "%s.lang" % app_id, "%s.svg" % app_id, "docker-compose.yml"):
        normalize_lf(os.path.join(work, name))

    out_dir = os.path.join(DIST, app_id)
    os.makedirs(out_dir, exist_ok=True)
    asset = "%s_%s.tar.gz" % (app_id, arch)
    out_path = os.path.join(out_dir, asset)
    with open(out_path, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, compresslevel=9) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                for name in ("config.ini", "%s.lang" % app_id, "%s.svg" % app_id, "docker-compose.yml"):
                    info = tar.gettarinfo(os.path.join(work, name), arcname=name)
                    info.uid = info.gid = 0
                    info.uname = info.gname = "root"
                    info.mode = 0o644
                    info.mtime = 0
                    with open(os.path.join(work, name), "rb") as fh:
                        tar.addfile(info, fh)
    digest = sha256_file(out_path)
    with open(out_path + ".sha256", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("%s  %s\n" % (digest, asset))
    return out_path, digest


def validate_package(app_id, arch):
    errors = []
    path = os.path.join(DIST, app_id, "%s_%s.tar.gz" % (app_id, arch))
    if not os.path.exists(path):
        return ["missing %s" % path]
    with tarfile.open(path, "r:gz") as tar:
        names = sorted(tar.getnames())
        expected = sorted(["config.ini", "%s.lang" % app_id, "%s.svg" % app_id, "docker-compose.yml"])
        if names != expected:
            errors.append("%s: root entries %s != %s" % (arch, names, expected))
        config = json.loads(tar.extractfile("config.ini").read().decode("utf-8"))
        if config.get("id") != app_id:
            errors.append("config.ini id mismatch")
        if config.get("platform") != arch:
            errors.append("config.ini platform mismatch")
        lang = tar.extractfile("%s.lang" % app_id).read().decode("utf-8")
        for lang_key in LANG_KEYS:
            if "[%s]" % lang_key not in lang:
                errors.append("lang missing %s" % lang_key)
                continue
            block = lang.split("[%s]" % lang_key, 1)[1].split("\n[", 1)[0]
            for field in ("name", "auth", "descript"):
                match = re.search(r'^%s = "(.*)"$' % field, block, re.M)
                if not match or not match.group(1).strip():
                    errors.append("%s: %s empty" % (lang_key, field))
        svg = tar.extractfile("%s.svg" % app_id).read().decode("utf-8")
        if "<svg" not in svg or "viewBox" not in svg:
            errors.append("svg missing svg/viewBox")
        compose = tar.extractfile("docker-compose.yml").read().decode("utf-8")
        if "x-app-meta:" not in compose:
            errors.append("compose missing x-app-meta")
        if "privileged: true" in compose or "network_mode: host" in compose:
            errors.append("compose uses privileged/host network")
        if "/Volume*" in compose:
            errors.append("compose uses /Volume* wildcard")
        try:
            import yaml  # type: ignore
            yaml.safe_load(compose)
        except ImportError:
            pass
        except Exception as exc:
            errors.append("yaml parse error: %s" % exc)
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--arch", choices=ARCHES, action="append")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    arches = args.arch or ARCHES
    secrets_map = load_secrets()
    if not args.check:
        for app_id in APPS:
            for arch in arches:
                out, digest = build_one(app_id, arch, secrets_map)
                print("built %-30s %s" % (os.path.relpath(out, ROOT), digest[:16]))

    errors = []
    for app_id in APPS:
        for arch in ARCHES:
            errors.extend(validate_package(app_id, arch))

    if errors:
        print("\nVALIDATION FAILED")
        for err in errors:
            print(" -", err)
        sys.exit(1)
    print("\nvalidation: %d packages OK" % (len(APPS) * len(ARCHES)))


if __name__ == "__main__":
    main()
