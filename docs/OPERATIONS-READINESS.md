# 性能基线、恢复演练与预部署验证

后续已连续完成性能优化、真实本地TLS与跨OS恢复；最新结果和整体交付边界见 LOCAL-DELIVERY.md。下文保留原基线与阶段验收，不能作为最新性能结果。

日期：2026-11-25，Asia/Shanghai。本阶段交付独立本机 HTTP 性能工具、覆盖最新业务快照的恢复演练、部署检查脚本及隔离预部署配置。公开发布、异机灾备和生产容量仍需要目标环境验证。

## 数据类型与测量范围

| 内容 | 性质 | 使用边界 |
|---|---|---|
| 商品、报价、买家、地址、订单和成本 | simulation，全部构造数据 | 不作为真实经营或供应商记录 |
| HTTP 延迟、吞吐、备份/恢复耗时、错误数 | 本机实际测量，measurement_kind 单独标注 | 仅适用于报告记录的环境和负载，不是公开市场指标 |
| 项目既有公开行业统计 | 独立的 public_survey_estimate 来源版本 | 本轮未新增或重新核查；不由模拟订单计算替换 |

原始报告保留在 evidence/，不含密码、会话令牌、地址正文或 API Key。报告存在时工具拒绝覆盖，以便保留各轮测量。早期报告作为历史记录保留，最终报告用 final 文件名区分。

## 可复现的本机 HTTP 基线

```powershell
$env:PYTHONUTF8='1'
$env:TEMP='D:/Codex_Projects/tmp'
$env:TMP=$env:TEMP
.venv/Scripts/python.exe scripts/commerce_benchmark.py --orders 1000 --samples 120 --concurrency 1,4,8 --output reports/benchmark-new.json
```

工具新建临时模板数据库，包含两件模拟商品、1000 笔取消订单、来源快照和 120 个虚构买家。每个并发级别从同一模板重新复制，不向已有演示站施压。启动自有单 worker uvicorn 子进程，仅监听随机本机端口，并校验唯一商品 ID 后才写入；退出时只终止自己创建的进程，清理临时数据库。

每组先预热 5 次订单查询，再测 120 次卖家订单列表（每页30）及 120 条买家流程。每条流程包括购物车写入、账号结算、卖家取消，共 3 次串行 HTTP 请求；每条使用独立预置买家/会话/地址，保留原有限流与 CSRF 校验。报告延迟是整条流程，吞吐单位为流程/秒，不能当作单个接口 QPS。p50/p95/p99 用 nearest-rank，样本量有限，未给置信区间。

每组另测 12 个访客请求争抢 3 件库存；预期 3 次成功、9 次409，随后取消成功订单恢复库存，并做只读业务校验。预期售罄不混入主测量的错误率。各组都从相同初始订单数开始，写入后的订单数为1123。

首次尝试把全部写入集中到一个访客来源，触发既有30次限流，返回429；该轮中止，没有登记为通过的性能报告。随后采用独立模拟买家，未放宽应用限流。最终测量期间没有同时运行本轮构建或测试，但系统其他背景负载未完全隔离。

结果见 [最终原始性能报告](evidence/benchmark-final-2026-11-25.json)。这是闭环、固定请求数的短时基线：没有 TLS、卖家 Key 鉴权、密码计算、真实支付或外部服务延迟，也未做持续负载、故障注入或峰值容量认证。并发提高时尾部延迟上升，不能据此线性外推产能；应先分解查询/序列化和写锁耗时，再按同一方法对比优化。

本次实测环境为 Windows 10、Python3.13.14、SQLite3.53.1，系统报告16个逻辑CPU；单进程。下表是最终一次测量，所有主样本均返回200、错误数0；三个并发级别的库存争抢均为3次成功和9次预期409，一致性 issues=[]。

| 并发 | 订单列表请求/秒 | 列表P95 ms | 列表P99 ms | 三请求流程/秒 | 流程P95 ms | 流程P99 ms |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 26.65 | 40.525 | 44.184 | 16.91 | 78.358 | 97.983 |
| 4 | 30.91 | 136.536 | 157.306 | 31.39 | 283.043 | 486.582 |
| 8 | 28.25 | 315.676 | 354.422 | 31.77 | 1041.018 | 1860.431 |

主测量合计720个样本、1440个HTTP请求，不含预热、库存争抢和就绪检查。8并发时流程P99约1.86秒，后续优化应以减少尾部等待和重复工作为目标，不能用“请求全部成功”替代延迟目标。

## 恢复演练与实际修复

```powershell
.venv/Scripts/python.exe scripts/commerce_restore_drill.py --output reports/recovery-new.json
```

演练新建完整业务临时库，包括模拟报价、指标场景、利润比较、商品、买家账号/地址/会话和11笔订单。保持源连接打开，在 WAL 中提交额外候选记录后执行在线备份，恢复到新文件。先在一致读事务中比较全部表行数与内容 SHA256，检查 schema25、数据库及外键完整性；再验证旧订单的比较/售后/公开参考来源、买家密码登录与订单所有权，并执行新的下单、模拟支付和退款。恢复验证后的订单数为12，业务一致性无异常；源库摘要保持不变。

首次演练发现 backup.snapshot 用 sqlite3 连接上下文管理事务，却没有立即关闭连接，导致 Windows 无法删除被占用的临时备份文件。现改用 contextlib.closing，成功与异常路径都释放连接，增加文件立即重命名及完整演练回归。[Python 官方说明](https://docs.python.org/3.13/library/sqlite3.html#how-to-use-the-connection-context-manager)明确区分了事务上下文和连接关闭；在线复制使用 [SQLite Backup API](https://sqlite.org/backup.html)。

结果见 [最终原始恢复报告](evidence/recovery-final-2026-11-25.json)。记录的 backup_ms/restore_ms 只计复制调用，不是服务恢复 RTO。本次是同机、小库、人工触发演练，不能认定生产 RPO/RTO，也未验证机器丢失后的异机恢复。实际数据库备份含买家资料，必须与这里的脱敏结果报告分开保存，不能提交仓库。

最终一次备份调用23.117ms、恢复调用35.218ms；原库与恢复库全部表内容摘要一致，已提交WAL记录包含在内。报告只输出表行数和摘要，不输出买家资料。

## 隔离预部署配置与检查

compose.protected.yaml 是独立配置，使用单独命名卷，不覆盖 compose.yaml 或宿主数据库：

```powershell
docker compose -f compose.protected.yaml config --quiet
docker compose build --build-arg PYTHON_IMAGE=mcr.microsoft.com/devcontainers/python:3.13
docker compose -f compose.protected.yaml up -d --no-build --wait
docker compose -f compose.protected.yaml exec -T app python scripts/commerce_preflight.py --profile protected
docker compose -f compose.protected.yaml exec -T app python scripts/commerce_protected_probe.py
```

配置开启卖家鉴权及 Secure Cookie，关闭同步分析入口，继续 mock/hash；单 worker、非 root、只读根文件系统、独立可写 data 卷及受限 tmpfs，移除 capabilities，启用 no-new-privileges，约束为1CPU、512MiB、128PID。没有宿主端口映射，网络 internal=true；这些定义分别见 [Docker 容器配置](https://docs.docker.com/reference/compose-file/container-spec/)与[内部网络说明](https://docs.docker.com/reference/compose-file/networks/#internal)。这些资源值只是本次预部署配置，不是容量结论。

预检输出只含白名单配置结果，校验 schema、模拟模式、单 worker、鉴权、Cookie、同步分析及数据库完整性。数据库不存在或不可读时输出 blocked、退出2，不创建空库或打印环境中的密钥。worker数量是声明值，仍需核对实际容器命令。默认演示配置不能通过 protected 检查；不能把关闭鉴权的演示站直接当作公网配置。

protected_probe 在容器内部用 HTTP 验证无 Key 为401、owner/viewer身份、只读写入为403、Secure/HttpOnly/SameSite Cookie标记和跨源登录拒绝。临时生成的测试 Key 在退出前撤销，不在结果或日志中输出明文。这里只验证 Cookie 标记，未在 HTTPS 浏览器中验证登录完整链路。预检即使通过，public_release 仍为 not_verified，不等于已经公开发布。

实际结果：[隔离预部署报告](evidence/predeployment-2026-11-25.json)中配置与 HTTP 探针均通过；Docker 检查确认根文件系统只读、没有宿主端口映射、网络为内部网络、资源限制与定义相符。[运行身份报告](evidence/predeployment-runtime-2026-11-25.json)确认UID10001、PID1命令为单worker、未撤销Key数量为0。[默认演示配置报告](evidence/preflight-demo-2026-11-25.json)按预期 blocked、退出2，拒绝了关闭鉴权/安全Cookie及开启同步分析的配置；数据库本身可读且完整性正常。隔离预部署容器已正常停止，命名卷保留。

预部署验证完成后可用 docker compose -f compose.protected.yaml stop 停止，保留命名卷；不要使用 --volumes 清理替代正常停止。日常演示仍使用原本的8027/8031入口。

## 生产推进顺序

| 优先级 | 产物 | 验收条件 |
|---|---|---|
| P1 | 查询、响应序列化与写锁的耗时分解，必要时缩小列表快照载荷 | 保留当前原始基线，使用同一数据规模和负载比较，库存及来源追踪不退化 |
| P1 | 目标环境的 TLS 入口、域名和可信代理配置 | 浏览器验证 Secure Cookie、Origin/CSRF、认证及退款权限；应用保持内部访问 |
| P1 | 异机备份存储、保留策略和恢复脚本 | 将指定快照在另一台机器恢复，校验内容、来源和业务操作，测量完整服务恢复时间 |
| P1 | 明确容量与可用性目标的持续负载报告 | 包含鉴权、密码计算、真实网络条件与资源监测；据证据决定是否迁移 PostgreSQL |
| P2 | 公开访问所需的账号验证、找回、反滥用和监测告警 | 使用目标环境实际验证；供应商仍全部模拟，不引入真实供应商依赖 |

本轮未指定云账号、域名、预算或正式业务 SLO，因此没有创建付费资源、变更 DNS、推送仓库或执行公网发布。CI 已加入比较重放与恢复命令，远端运行仍待实际触发验证。

## 最终回归与交付状态

全量 **880 passed、1 xfailed、1 warning，51.03秒**，共881项；本轮新增5项运维测试，并增强既有备份测试，校验连接释放后文件可立即重命名。测试覆盖延迟口径、一致读摘要/WAL、预检条件、缺库退出且不泄漏环境Key、完整恢复与源库不变。既有 xfail 为评论规则未覆盖 died 隐性故障，warning 为 TestClient/httpx 弃用提示，均未冒充本轮修复。

数据库空库 up/down/up 到25指纹一致。最终本机Docker演示烟测通过，两商品结算、幂等模拟支付、整单退款与库存恢复正常；只读业务校验核对2件商品、7笔订单，issues=[]。本轮没有修改前端业务流程，未重复声称新增浏览器验收。

当前性能基线、恢复演练与预部署检查阶段已完成。下一步优先进行读接口载荷/序列化与并发写入尾延迟的定位优化，保留本轮原始测量再复测；公网条件仍按上表单独验收。
