# TOS 7 Docker 应用打包

把 7 个 Docker 应用整理成 TOS 7 应用商店可提交的 Docker 包（`config.ini` + `<appid>.lang` + `<appid>.svg` + `docker-compose.yml`），并按每个应用一个独立 GitHub 仓库、x86_64/aarch64 双架构发布。

## 应用清单

| 应用 | 应用 ID | 镜像（Docker Hub） | Web 端口 | 数据卷 | 架构 | 风险 |
|---|---|---|---|---|---|---|
| FileFlows | `fileflows` | `revenz/fileflows` | 19200 | `/app/Data`、`/app/Logs`、`/app/temp` | amd64/arm64 | 镜像以 PUID/PGID 运行 |
| Lychee | `lychee` | `lycheeorg/lychee` | 18081 | `/conf`、`/uploads`、`/sym`（SQLite） | amd64/arm64 | 镜像主进程为 root |
| code-server | `coder-code-server` | `codercom/code-server` | 18082 | `/home/coder` | amd64/arm64 | 密码首次启动随机生成 |
| BookStack | `bookstack` | `linuxserver/bookstack` + `mariadb:10.11` | 18083 | `/config`、数据库目录 | amd64/arm64 | 初始管理员需立即改密 |
| Stirling-PDF | `stirling-pdf` | `stirlingtools/stirling-pdf` | 18084 | `/configs`、`/logs` 等 | amd64/arm64 | 默认关闭登录 |
| Dozzle | `dozzle` | `amir20/dozzle` | 18086 | Docker 套接字（只读）、`/data` | amd64/arm64 | 套接字权限较高 |
| AppFlowy | `appflowy` | `appflowyinc/appflowy_cloud` 等 6 个服务 | 18085 | 多套卷 | amd64/arm64 | **高风险，见下** |

> `code-server` 与 `codeserver` 已被平台其他开发者占用，应用 ID 使用 `coder-code-server`；GitHub 仓库仍为 `Irvingfei/tos-code-server`。

产物在 `dist/<appid>/`：`<appid>_x86_64.tar.gz`、`<appid>_aarch64.tar.gz` 及对应 `.sha256`。

## 打包

```bash
python build.py                 # 生成 7 应用 × 2 架构
python build.py --arch x86_64   # 只生成一个架构
python build.py --check         # 只校验已有产物
```

构建会校验：包根只含 4 个文件、config.ini JSON、14 种语言节点及 name/auth/descript、SVG 的 viewBox、compose YAML 可解析、无 privileged / host 网络 / `/Volume*`。

BookStack 与管理后台密码在首次构建时随机生成并保存在 `.secrets.json`（已加入 `.gitignore`，不要提交）。重复构建会复用这些值。

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

GitHub 仓库默认建在 `Irvingfei` 名下，可用 `GITHUB_OWNER` 覆盖。每个仓库一个 `v1.0.0` Release，内含双架构包与 `.sha256`。

## 源码仓库

- 每个应用仓库的 `src/` 保存该应用的打包源码：`config.x86_64.ini`、`config.aarch64.ini`、`docker-compose.yml`、`<appid>.lang`、`<appid>.svg`。compose 中的 `@@...@@` 为构建时替换的占位符。
- 打包工具链发布在 `https://github.com/Irvingfei/tos-docker-apps`（不含 `.env` 与 `.secrets.json`）。

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

**第三方合规**
- 审核标准包含“不得侵犯第三方商标/版权”。本工程使用自绘 SVG 图标，README 中注明非官方封装；仍建议确认你有权将这些第三方应用以自己的开发者名义上架。

## 未验证项

当前环境没有 Docker，也没有 TOS 设备，因此没有做安装/启动/端口/健康检查的实机验证。提交前请在 TOS 7 上逐个安装验证，尤其是 BookStack（APP_URL 与首次迁移）和 AppFlowy（基础地址）。
