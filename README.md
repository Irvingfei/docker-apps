# TOS 7 应用打包

把 9 个 Docker 应用和 1 个 Deb 应用整理成 TOS 7 应用商店可提交的包，并按每个应用一个独立 GitHub 仓库、x86_64/aarch64 双架构发布。

- Docker 包：`config.ini` + `<appid>.lang` + `<appid>.svg` + `docker-compose.yml`
- Deb 包：`DEBIAN/` 维护脚本 + `usr/local/<appid>/`（配置、语言、图标、`webui.bz2`、`nginx/<appid>.conf`、systemd 单元）

## 应用清单

| 应用 | 应用 ID | 类型 | 镜像 / 来源 | Web 端口 | 数据 | 架构 | 风险 |
|---|---|---|---|---|---|---|---|
| FileFlows | `fileflows` | Docker | `revenz/fileflows` | 19200 | `/app/Data`、`/app/Logs`、`/app/temp` | amd64/arm64 | 镜像以 PUID/PGID 运行 |
| Lychee | `lychee` | Docker | `lycheeorg/lychee` | 18081 | `/conf`、`/uploads`、`/sym`（SQLite） | amd64/arm64 | 镜像主进程为 root |
| code-server | `coder-code-server` | Docker | `codercom/code-server` | 18082 | `/home/coder` | amd64/arm64 | 密码首次启动随机生成 |
| BookStack | `bookstack` | Docker | `linuxserver/bookstack` + `mariadb:10.11` | 18083 | `/config`、数据库目录 | amd64/arm64 | 初始管理员需立即改密 |
| Stirling-PDF | `stirling-pdf` | Docker | `stirlingtools/stirling-pdf` | 18084 | `/configs`、`/logs` 等 | amd64/arm64 | 默认关闭登录 |
| Dozzle | `dozzle` | Docker | `amir20/dozzle` | 18086 | Docker 套接字（只读）、`/data` | amd64/arm64 | 套接字权限较高 |
| AppFlowy | `appflowy` | Docker | `appflowyinc/appflowy_cloud` 等 6 个服务 | 18085 | 多套卷 | amd64/arm64 | **高风险，见下** |
| Dreeve | `dreeve` | Docker | `robiningelbrecht/dreeve:v5.9.1` | 18088 | `build`、`storage`、`watch`、`backups` | amd64/arm64 | 初始管理员密码固定为 Dreeve-2026 |
| wger | `wger` | Docker | `wger/server:2.7` + PostgreSQL/Redis/Celery/nginx | 18089 | PostgreSQL、静态与媒体文件 | amd64/arm64 | 7 个容器，首次启动 5–10 分钟 |
| CookCLI | `cookcli` | Deb | 上游 0.41.1 静态 musl 二进制 | 18087 | `cookcli-data` 共享文件夹 | amd64/arm64 | 默认无登录，同网段可改食谱 |

> `code-server` 与 `codeserver` 已被平台其他开发者占用，应用 ID 使用 `coder-code-server`；GitHub 仓库仍为 `Irvingfei/code-server`。

Docker 产物在 `dist/<appid>/`：`<appid>_x86_64.tar.gz`、`<appid>_aarch64.tar.gz` 及对应 `.sha256`。
Deb 产物在 `dist/cookcli/`：`cookcli_x86_64.deb`、`cookcli_aarch64.deb` 及对应 `.sha256`。

## 打包

```bash
python build.py                 # Docker 应用 × 2 架构
python build.py --arch x86_64   # 只生成一个架构
python build.py --check         # 只校验已有产物

python build_deb.py             # CookCLI deb × 2 架构（首次会下载并校验上游 musl 包）
python build_deb.py --check     # 只校验已有 deb
```

Docker 构建会校验：包根只含 4 个文件、config.ini JSON、14 种语言节点及 name/auth/descript、SVG 的 viewBox、compose YAML 可解析、无 privileged / host 网络 / `/Volume*`。
Deb 构建会校验：ar 容器与 control/data 成员、Package/Version/Architecture、`usr/local/cookcli/` 下的配置/语言/图标/`webui.bz2`/nginx 单元、config.ini（`application_type=deb`、`open_path=true`、`path=/cookcli/`）、ELF 架构、nginx 只含 location 块。

BookStack、Dreeve、wger 的密码与密钥在首次构建时生成并保存在 `.secrets.json`（已加入 `.gitignore`，不要提交）。重复构建会复用这些值；cookcli 无构建期密钥。

## 发布

1. 配置 `GITHUB_TOKEN`（repo 权限）与 `TDP_TOKEN`（app:write、version:write 等）。
2. 预演：
   ```bash
   python publish_github.py     # 打印将创建的仓库/Release
   python submit_tdp.py         # 打印将创建的应用/版本
   ```
3. 正式执行：
   ```bash
   python publish_github.py --apply
   python submit_tdp.py --apply
   ```
4. 可单独操作某个应用：`--app fileflows`；单独架构：`--arch x86_64`。

GitHub 仓库默认建在 `Irvingfei` 名下，可用 `GITHUB_OWNER` 覆盖。每个仓库一个 `v1.0.0` Release，内含双架构包与 `.sha256`：Docker 应用为 `<appid>_<arch>.tar.gz`，CookCLI 为 `<appid>_<arch>.deb`。TOS 平台按扩展名识别包类型，CookCLI 走 deb 单包流程。

## 源码仓库

- 每个应用仓库的 `src/` 保存该应用的打包源码：`config.x86_64.ini`、`config.aarch64.ini`、`docker-compose.yml`、`<appid>.lang`、`<appid>.svg`。compose 中的 `@@...@@` 为构建时替换的占位符。
- 打包工具链发布在 `https://github.com/Irvingfei/docker-apps`（不含 `.env` 与 `.secrets.json`）。

```bash
python publish_sources.py --apply   # 上传工具链和应用源码
```

## 高风险说明

**AppFlowy**
- 官方 compose 依赖的 `minio/minio` 已不在 Docker Hub（返回 404），包内改用社区镜像 `elestio/minio`，不符合“优先官方/验证镜像”的审核取向。
- AppFlowy Cloud 要求 `APPFLOWY_BASE_URL` 为浏览器可访问的绝对地址，而 TOS compose 是静态配置、无法在安装时注入 NAS 地址。包内暂写为 `http://localhost:18085`，安装后必须手工改成实际地址并重建容器，否则网页端无法连接后端。
- 服务数量多（数据库、Redis、MinIO、GoTrue、Cloud、Web、网关），且包含多个固定密钥，通过人工安全审核的概率低。**建议先不提交，或单独与平台沟通。**

**Dozzle**
- 通过只读挂载 `/var/run/docker.sock` 读取容器日志，等价于较高宿主机权限；镜像默认以 root 运行。功能可用，但可能触发安全审核。

**Dreeve**
- `APP_URL` 只支持站点根路径，包内为 `http://localhost:18088`；安装在反代子路径下时跳转与回调用不了，需要改为实际访问地址。
- 使用固定管理员凭据（`.secrets.json` 中的 bcrypt 哈希），首次登录后应立刻在应用内改密码。镜像以 `PUID/PGID=1000` 运行。
- dreeve 官方仓库较新、发行版迭代快；包固定 `v5.9.1`，升级需重建。

**wger**
- 首次启动会执行数据库迁移和 `collectstatic`，初始化需数分钟；期间 nginx 可能返回 5xx，属正常。
- 启动顺序依赖 `init` 容器先完成 chown（UID 1000/999），若共享文件夹权限被平台改写可能启动失败。
- `SITE_URL` 写死为 `http://localhost:18089`，注册邮件和绝对链接会指向该地址，需按实际地址修改。
- 共 7 个容器（含 PostgreSQL/Redis），资源占用较高。

**CookCLI（deb）**
- 二进制为上游静态 musl 构建，按 x86_64/aarch64 分别下载并校验上游 `.sha256`；不依赖 Docker。
- 以外部打开方式挂到 `/cookcli/`，nginx 只做前缀转发，`Host` 透传；上游对 Host 有校验，改动反代头可能导致请求被拒。
- 食谱目录优先用共享文件夹 `/Volume*/cookcli-data/recipes`，安装时通过 `ter_share_add` 创建；若平台没有共享目录机制则回落到 `/usr/local/cookcli/data/recipes`。
- 首次安装后没有示例食谱，页面可能为空，需自行放入 `.cook` 文件。

**第三方合规**
- 审核标准包含“不得侵犯第三方商标/版权”。本工程使用自绘 SVG 图标，README 中注明非官方封装；仍建议确认你有权将这些第三方应用以自己的开发者名义上架。

## 未验证项

当前环境没有 Docker，也没有 TOS 设备，因此没有做安装/启动/端口/健康检查的实机验证。提交前请在 TOS 7 上逐个安装验证，尤其是 BookStack（APP_URL 与首次迁移）、AppFlowy（基础地址）、Dreeve（APP_URL 与管理员登录）、wger（初始化与 init 容器权限）、CookCLI（`/cookcli/` 反代与 Host 校验）。
