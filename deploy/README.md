# 服务器部署准备与安全测试

这是测试环境配置，不是已经部署完成的服务。运行前先完成 `docs/SERVER_DEPLOYMENT_PLAN.md` 的本地保护步骤。真实 MQTT 在 Compose 中被强制关闭，不要为了联调直接移除该保护；设备接口、访问限制、持久任务恢复和重复执行保护仍须单独验收。

## 本地电脑

保留原来的 `.venv`、启动脚本和 `backend/.env`。不需要本机安装 Docker。

在项目根目录用 PowerShell 运行 `./deploy/backup-local.ps1`，它会在项目旁的 `deployment-backups` 创建备份，复制 Git 管理及未忽略文件、存在的 `.env` 和 MQTT 历史，逐文件核对 SHA256 并限制备份目录 ACL。备份可能含真实密钥，不上传 GitHub，也不传到公开下载目录。备份不包含 `.venv`，历史有活跃写入时不是事务快照；需要完整历史快照时先停止本地写入，再另做一次备份。

恢复前先验证 `manifest.json`，将 `snapshot` 恢复到一个新目录并检查，不直接覆盖现有项目。使用当前 `.venv` 验证已恢复源码时需要明确指定解释器；重建环境时依赖下载仍需联网。正式备份恢复演练尚需另行执行。

## 服务器预备检查（只读）

以下 Linux 命令只在服务器终端执行。不要在 Windows PowerShell 执行。

```bash
id
sudo -n true
command -v docker
docker --version
docker compose version
ss -lnt
sudo ufw status verbose
timedatectl status
```

没有 Docker、Compose 或 `sudo -n` 失败时，保留输出后停止该步骤，不运行来源不明的一键安装命令。安装步骤要根据实际检查结果制定。本文件不自动修改 SSH、防火墙或系统软件。

## 服务器内部测试（Docker 安装及代码上传完成后）

本地可运行 `./deploy/package-source.ps1` 创建无密钥发布 ZIP。输出在项目旁 `deployment-releases`，仅打包明确允许的源码、JSON 数据和部署模板，不包含私有 `.env`、`.venv` 或历史。包内 manifest 记录基线提交、工作区状态及逐文件哈希；有未提交改动时必须视为候选包，不是正式版本。将 ZIP 及 `.sha256` 上传服务器，先用 `sha256sum -c` 核验，再解压到新的独立目录，不覆盖已有服务或配置。压缩包不含真实配置；不要用本地完整备份替代发布包上传。

首次上传后在服务器用 `python3 -m zipfile -e ARCHIVE.zip NEW_DIRECTORY` 解压（将占位符替换为实际名称），先确认 NEW_DIRECTORY 不存在。进入解压目录后，继续以下内部测试步骤。Docker 需要 sudo 的账号，应对下面所有 `docker compose` 命令加 `sudo`；不为省略 sudo 自动加入 docker 组。

前提：代码位于独立服务器目录，Docker / Compose 已核验，有足够磁盘，8877 未对公网开放。Compose 文件使用 JSON 格式，属于 YAML 的有效子集，需显式通过 `-f` 指定。

在服务器的项目根目录执行，`cp` 仅首次运行；若已有 `deploy/server.env`，不要覆盖：

不要重复执行 `cp -n`：部分系统会提示该选项行为不便携。以下先检查文件是否存在的写法不依赖 `-n`；出现过该警告但配置检查已通过时，不需要重建配置文件。

```bash
test -f deploy/server.env || (umask 077; cp deploy/server.env.example deploy/server.env)
chmod 600 deploy/server.env
docker compose -f deploy/compose.json config --quiet
docker compose -f deploy/compose.json build
docker compose -f deploy/compose.json up -d
docker compose -f deploy/compose.json ps
docker compose -f deploy/compose.json exec -T app python -c "import json,urllib.request; r=json.load(urllib.request.urlopen('http://127.0.0.1:8877/api/health')); assert r['status']=='ok' and not r['mqtt']['enabled']; print('health passed; MQTT disabled')"
```

不要把 `docker compose config` 的完整输出发到聊天：解析后的配置可能包含密钥，所以使用 `--quiet`。默认没有云端密钥，不进行付费调用。需要启用 AI / ASR 时，先配置受限访问方式，再在服务器编辑 `deploy/server.env`，不把密钥发到聊天。Docker 管理权限等同高权限，勿随意授权其他用户或开放 Docker API。

本配置只映射服务器 `127.0.0.1:8877`。公网浏览器打不开是预期行为，不要因此将绑定改成 `0.0.0.0`。域名审核期间可继续在服务器终端检查；必要时经已配置好的 SSH 建立本地隧道：

```text
ssh -N -L 18877:127.0.0.1:8877 ubuntu@SERVER_PUBLIC_IP
```

此命令在本地独立终端运行，将占用该终端，停止时按 Ctrl+C。本地浏览器访问 `http://127.0.0.1:18877`；此前应先确认 SSH 主机指纹及登录权限。隧道为临时个人测试，不是给其他人使用的正式网址。

### 构建时 PyPI 下载超时

Docker Hub 的镜像加速不负责 Python 包下载。若 `files.pythonhosted.org` 读取超时，先确认已将更新后的部署 Dockerfile 同步到服务器，并备份服务器旧文件；原始发布 ZIP 中没有后加的构建参数。

Dockerfile 默认仍使用官方 PyPI，读取超时 120 秒、连接重试 5 次。可仅对本次构建指定腾讯云官方 HTTPS 软件源，不改本机或服务器全局 pip 配置，不关闭证书验证，也不改变锁定依赖版本：

```bash
sudo docker compose --progress plain -f deploy/compose.json build --build-arg PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
```

如果镜像源未同步所需版本、返回错误或 TLS 失败，应保留错误再排查，不直接降低版本或添加 `--trusted-host`。构建参数只应包含公开软件源地址，不放账号和密钥。项目镜像只有成功构建后才进入下一步启动验收。

## 域名与备案就绪后（现在不要执行）

先核实备案、DNS、测试人员公网 IP 或 VPN 方案以及依赖安全审查，再启用 HTTPS 配置。`access.caddy.example` 默认拒绝全部业务请求，按实际访问来源配置后才允许内部使用；凭证不写前端。证书验证及续期必须保持所选挑战方式可达，不能用云防火墙规则误挡验证服务。

首次创建 `deploy/access.caddy`，审查并修改允许来源后，设置 `VD10_DOMAIN`。合并配置及入口校验方法如下（DOMAIN 替换为已准备好的真实域名）：

```bash
export VD10_DOMAIN=DOMAIN
docker compose -f deploy/compose.json -f deploy/compose.https.json config --quiet
docker compose -f deploy/compose.json -f deploy/compose.https.json run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose -f deploy/compose.json -f deploy/compose.https.json up -d
```

该入口不会自动启用 MQTT。未授予来源应返回 403；允许来源验证网页、WSS 和功能。不要转发外部提供的身份头作为可信用户。依赖锁是当前环境版本快照，不是安全扫描通过证明；公开使用前需审核基础镜像、Python 包和 Caddy 的漏洞及更新情况。

## 数据、停机及当前限制

- `app-data` 保存 MQTT 历史；目前工作流实时状态仍在应用内存，不能宣称已实现数据库恢复。软件测试时可重建服务，真实执行通道必须保持关闭。
- `caddy-data` 保存证书数据。不要用 `docker compose down -v` 删除数据卷。
- 临时停止内部测试服务：`docker compose -f deploy/compose.json stop`。未检查在途任务前，不做升级或重新下发任务。
- 依赖及基础镜像锁定版本仍需在 Linux 实际构建验证；本机无 Docker 时，不安装本机 Docker 来绕过这一限制。
- 发布、回滚、数据库恢复、限流、独立接口凭证及真实设备互锁属于后续工作，不因为存在这些准备文件就视为完成。

完整状态与下一步以 `docs/SERVER_DEPLOYMENT_PLAN.md` 为准。
