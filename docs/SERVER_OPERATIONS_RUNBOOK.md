# 服务器备份、更新回滚与 HTTPS 操作手册

更新日期：2026-10-27。所有 Linux 命令均在腾讯云服务器执行，除明确标注“本地 PowerShell”的步骤。出现错误先停止，不复制终端提示符或输出作为命令。此文档不是执行完成证明，进度以 SERVER_DEPLOYMENT_PLAN.md 为准。

## 当前状态与执行顺序

- 服务器：110.40.206.121，Ubuntu 24.04，项目目录 `/home/ubuntu/vd10-staging-20261027`。
- 项目通过 SSH 隧道可用，ASR、AI 编排、流程图、缺参补充、委托单识别及容器重启复测已通过。
- 域名 `firebox001.top` 的 ICP 备案审核中，正式公网入口未启用。
- 时间戳细项测试按用户要求暂缓。MQTT 禁用，不进行设备执行。
- 当前没有数据库任务恢复，容器重启后仍可工作的结论不代表在途任务状态已持久化。
- 现在先做 A（备份）与 B（核验），之后安排 C（恢复演练）；D（更新回滚）留作每次更新使用，E（HTTPS）在备案通过后执行。

## A. 备份当前可用服务器版本

### A1. 上传工具

将本地项目的 `deploy/server_backup.py` 上传到服务器 `/home/ubuntu/server_backup.py`。无需安装 Python 包，不修改本机环境。它不包含你的密钥，但生成的备份包含服务器真实配置。

先结束录音、编排、文档识别等请求，保存需要保留的文本和结果。确认没有其他人使用。备份期间会短暂停止并重新启动当前 app 容器，通常不影响 SSH 登录本身，实际时长取决于数据大小。

### A2. 执行备份

```bash
sudo python3 /home/ubuntu/server_backup.py --project /home/ubuntu/vd10-staging-20261027 --confirm-stop
```

工具将执行：

1. 确认 app 唯一、healthy、属于本项目、MQTT 禁用且数据挂载符合预期，不满足则拒绝操作。
2. 检查备份位置和可用磁盘，建立 `/var/backups/vd10/时间标识/`，仅管理员可访问。
3. 根据实际运行镜像 ID 创建独立 checkpoint 标签，并导出 `image.tar`，不再依赖重新下载才能回退。
4. 保存源码和配置为 `source-and-config.tar.gz`，包含 `deploy/server.env`，不包含 `.venv`、`.git` 等环境。
5. 短暂停止同一容器，复制 `/var/lib/vd10` 数据，保留 UID/GID；正常异常处理会尝试重新启动同一容器。
6. 等待重新 healthy，生成 `metadata.json`、`checksums.json`、`COMPLETE`，逐文件复核。

完成时输出 `Backup completed: /var/backups/vd10/具体目录`。保留这个路径。没有完成标记、备份报错或应用未恢复健康，均不能视为成功；保留部分文件排查，不自动删除或反复运行。

备份不包含进程内存任务、不包含整台服务器系统/SSH/Docker配置，也没有自动制作服务器外副本。此工具仅针对当前隔离测试环境；MQTT/真实设备启用后不能继续直接用于生产停机备份。

### A3. 隐私与磁盘

不要把备份包、源码配置压缩包、`.env` 内容或其截图发到聊天、GitHub或公开下载目录。备份含密钥，当前是权限隔离而非加密。需要服务器外副本时，先采用双方确认的加密方式，再传至本地受保护目录或受控存储；未完成前不能标为异地备份完成。

首次做一次完整镜像备份，每次发布前再做。暂不自动定时导出完整镜像，避免 40GB 磁盘被重复大文件占满；后续先验证恢复，再制定轻量日备份、保留周期和告警。不要自行执行 `docker system prune -a --volumes` 或删除不认识的数据卷。

## B. 备份核验

将 BACKUP_DIRECTORY 替换为 A2 输出的完整路径，不能原样粘贴占位符：

```bash
sudo python3 /home/ubuntu/server_backup.py --verify BACKUP_DIRECTORY
sudo docker compose -f /home/ubuntu/vd10-staging-20261027/deploy/compose.json ps
```

预期：文件校验通过，容器 healthy。保持本地 SSH 隧道开启，在网页再次生成一次流程，确认软件仍可用。

校验只证明备份文件与备份清单一致，不证明已成功恢复，也不证明旧版本无安全漏洞。

## C. 恢复演练（备份成功后单独安排）

不直接向当前运行目录或数据卷恢复。

1. 先校验备份，读取 `metadata.json` 确认 checkpoint 镜像标签与源目录；不要输出源码配置包内的密钥。
2. 如需验证离线恢复，用 `docker image load -i BACKUP_DIRECTORY/image.tar` 导入；这会导入 checkpoint 标签，不应覆盖 candidate 标签。
3. 新建独立恢复目录，审阅源码归档成员后提取至该目录，不覆盖现有项目。只恢复受保护、已校验的自有备份，不以 root 解压不可信归档。
4. 创建独立恢复测试容器和数据卷，使用独立项目名，例如 `vd10-restore-check`，端口仅 `127.0.0.1:18878`。当前 compose.json 固定了项目名，直接换目录仍会操作原服务，不能直接原样启动。
5. 在停止的恢复测试容器中复制备份数据并保留 UID/GID，实际挂载只能指向新的测试卷；不挂载原 app-data 卷。
6. 保持 MQTT 关闭，不连接真实执行模块。核对文件、启动健康、网页、能力查询及已有持久记录，不把不存在的内存任务“恢复”出来。
7. 验收后停止恢复测试容器。测试资源清理先确认准确名称，不使用全局清理命令。

上述具体恢复配置待备份路径及内容确认后再生成并审查，本节当前不是可直接运行的自动恢复脚本。恢复演练成功后，才将 P6-03 的恢复子项标为完成。

## D. 以后怎样更新与回滚

### D1. 更新前

本地开发、测试、提交代码；发布必须有确定版本和无密钥包。当前工作区部署改动尚未提交，不将 candidate 当成正式版本。

每次更新前先执行 A/B，记录：旧部署目录、旧源码版本、备份路径及 `metadata.json` 的 `releaseTag`。停止新增任务并通知使用者短暂维护。

### D2. 构建新版本（旧服务保持运行）

将无密钥发布包校验后解压到新的版本目录，不覆盖当前项目。只在服务器复制/配置必要凭证，并保持 `server.env` 权限 600，不能被模板覆盖。

以下 NEW_DIRECTORY、NEW_RELEASE_TAG 必须替换为实际值；标签仅使用小写英文、数字和短横线，不使用共享的 candidate 标签覆盖旧镜像：

```bash
sudo env VD10_RELEASE=NEW_RELEASE_TAG docker compose --progress plain -f NEW_DIRECTORY/deploy/compose.json build --build-arg PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
```

新镜像先在独立项目名、端口和数据卷中做检查。当前主项目使用固定 Compose 名 `vd10-workflow`，不同目录直接 up 不会成为独立环境，反而会切换同一组服务。

### D3. 发布切换

只有新版本测试、访问控制、配置兼容及回退准备通过，才从新目录启动同一个主项目。维护窗口里保存输入、结束录音并等待在途请求结束。

```bash
sudo env VD10_RELEASE=NEW_RELEASE_TAG docker compose -f NEW_DIRECTORY/deploy/compose.json up -d --no-build --pull never --wait --wait-timeout 120
```

现有名为 `vd10-workflow_app-data` 的卷会被同项目继续使用，因此这不是数据隔离部署。如果变更了数据结构，发布前必须另做迁移和向后兼容验证，不能盲目复用。

检查 healthy、回环端口、MQTT 禁用、网页和核心流程后才结束维护。已启用 HTTPS 时还必须带同一套 HTTPS 配置和正确域名变量，不能用内部测试命令替代正式发布命令。

### D4. 失败回滚

保持旧目录和旧 `server.env`，用备份记录的 checkpoint 标签启动。OLD_RELEASE_TAG 是 `metadata.json` 的 `releaseTag`，不是完整镜像名：

```bash
sudo env VD10_RELEASE=OLD_RELEASE_TAG docker compose -f OLD_DIRECTORY/deploy/compose.json up -d --no-build --pull never --force-recreate --wait --wait-timeout 120
```

这只切换程序及其运行配置，不自动恢复数据。如果新版本改变了数据结构或造成数据错误，先停下并核对备份，恢复到独立卷验收，不能直接覆盖真实数据。

新旧版本都不得因恢复、重启或重复请求而重新执行物理任务。当前 MQTT 关闭；真实设备接入后需要另行设计排队、幂等和状态核对。

### D5. 用户怎样获取更新

服务器切换后，新打开或刷新网页会获取更新。已经打开的页面不会自动热替换现有 JavaScript；当前尚未实现版本提示功能。第一版通知用户保存后刷新，之后再增加版本检测，不强制刷新正在录音的页面。

## E. 备案通过后怎样启用域名与 HTTPS

当前仅准备，不启用正式公网入口。

1. 确认 `firebox001.top` 在备案控制台明确显示通过，并按要求处理备案标识及其他上线手续，不把域名实名当作备案完成。
2. DNSPod 免费版添加 A 记录，建议 `lab.firebox001.top` 指向 `110.40.206.121`。本建议尚未作为最终入口确认；若选择根域名，则主机记录为 `@`。没有配置 IPv6 服务前不添加 AAAA。
3. 确认测试用户来源：固定公网 IP 用白名单；不固定则先讨论 VPN 或其他访问凭证。没有访问限制前不匿名开放付费接口或设备接口。
4. 复核 Caddy 和应用依赖安全更新。现有配置版本仅经过功能构建，不代表漏洞扫描通过。
5. 上传并核对最新 Caddy/HTTPS 配置，创建服务器 `deploy/access.caddy`。默认模板拒绝全部请求，按真实来源审查后开放，不能删光限制来“修复”403。
6. 防火墙放行所需80/443，8877保持回环绑定，SSH保持受限。HTTP-01/TLS-ALPN-01证书校验需要对应入口可达；应用白名单不能误阻断证书验证和续期。若入口必须整体网络隔离，再单独设计DNS-01及最小权限解析凭证。
7. 设置选定域名，执行 Compose/Caddy 原生校验，再启动 HTTPS 服务：

```bash
sudo env VD10_DOMAIN=lab.firebox001.top docker compose -f /home/ubuntu/vd10-staging-20261027/deploy/compose.json -f /home/ubuntu/vd10-staging-20261027/deploy/compose.https.json config --quiet
```

若已更新为其他部署目录或镜像标签，必须同步使用正确的路径及 VD10_RELEASE，不能直接使用这里的旧目录示例。完整 Caddy 校验和启动命令见 `deploy/README.md`，启用前先确认实际配置。

8. 验收允许来源正常、拒绝来源403或被网络拒绝、HTTPS无警告、语音WSS及ASR、编排和委托单正常，并检查证书存储卷和续期错误告警。
9. 其他用户直接访问HTTPS域名，不再需要SSH隧道；自己的旧隧道仍可临时保留。MQTT仍关闭，机器人模块联调是独立阶段。

## F. 每日维护和自动化边界

- 当前手工备份、更新、回滚需先完成一次完整验收，之后再添加定时任务或GitHub自动发布。
- 后续建议：每日轻量数据/配置备份、发布前完整镜像备份、服务器外加密副本及恢复抽查。先确认保留周期、磁盘预算和异地存储，再实施定时器，不能只写文档就标为完成。
- 配置CPU、内存、磁盘、服务器流量及云API费用告警。不要为了备份停用设备互锁或绕过人工确认。
- 整机重启测试安排在备份及恢复路线确认后：检查Docker开机启动和unless-stopped策略，保证app不是手动停止状态；重启后SSH隧道会断，需要重新连接再检查healthy和网页。

## 官方依据

- Docker数据复制与保留UID/GID：https://docs.docker.com/reference/cli/docker/container/cp/
- Docker镜像导出：https://docs.docker.com/reference/cli/docker/image/save/
- 容器重启策略：https://docs.docker.com/engine/containers/start-containers-automatically/
- Caddy自动HTTPS：https://caddyserver.com/docs/automatic-https
- 腾讯云轻量服务器防火墙：https://cloud.tencent.com/document/product/1207/44577
