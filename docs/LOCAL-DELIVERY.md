# 本地项目交付与外部部署边界

用户已明确后续仅在本机部署与验证，本轮已完成，最新操作与验收见LOCAL-DEPLOYMENT.md。本文后面的公网部署条件保留为可选扩展，不再作为当前任务的阻塞。

日期：2026-11-25，Asia/Shanghai。按既定范围连续完成性能优化、真实TLS验证、跨系统恢复及发布候选，不在各阶段完成处结束执行。当前交付定位仍为个人可运行、可演示、可在简历中解释的跨境选品与经营系统，不宣称已是公众生产服务。

## 整体可用范围

| 链路 | 已完成与证据 |
|---|---|
| 评论到商品 | 离线构造评论证据、候选SKU、独立站成本门禁、版本化决策、商品草稿、库存和上架；Amazon/FBA决策保留独立口径 |
| 采购与指标 | 本地模拟询价/报价/样品状态流、两报价五种情景比较、MOQ/交期约束、指标来源版本与明确假设；公开销售占比不转成SKU概率 |
| 买家与交易 | 会话、地址、购物车、多商品原子结算、幂等模拟支付、模拟发货/完成、整单退款审核与净损失登记 |
| 权限与追踪 | owner/operator/viewer、租户与买家所有权、CSRF、事务内审计、不可覆盖快照、订单到原决策的追踪 |
| 经营与运维 | 预测/记录贡献偏差、只读业务校验、在线备份/新库恢复、性能原始报告、真实本地HTTPS验证、受保护与TLS发布候选配置 |
| 演示与简历 | COMMERCE-DEMO.md、COMMERCE-PORTFOLIO.md及各阶段验收记录；不报告虚构GMV、转化率、真实供应商结果或生产QPS |

供应商身份、报价、全部交互与状态变化仍为模拟；交易和成本也为模拟。HTTP延迟、恢复耗时和验证结果是实际观测，报告用measurement_kind与fixture_data_kind区分。既有公开统计仍有独立来源目录，本轮未新增市场统计。

## 性能定位与修复

30单页面原先逐订单读取订单及明细，领域查询为62条SQL，序列化载荷约429834字节。新增批量读取和摘要视图，领域查询降为4条SQL；工作台使用view=summary，约13436字节，来源在展开时再读取。默认view=full保留旧响应行为，完整订单详情仍按原租户权限读取，历史快照没有裁剪或重写。API在同一页内使用一致读事务，跨多页的状态仍按每次查询解释。

完整模式自身的领域查询P95从6.619ms到6.487ms，不能据此宣称显著加速。主要改进来自工作台摘要投影：查询P95为2.177ms、JSON编码P95为0.111ms。完整模式与摘要视图输出粒度不同，优化后的列表仍保留页面展示与操作所需的字段，通过按需详情保证可追溯。

同一文件数据库的单进程写事务增加FIFO准入，减少线程直接争抢SQLite写锁时的尾部等待。不同数据库各自排队；嵌套事务复用外层，超时及中断清理排队项。SQLite BEGIN IMMEDIATE、回滚、库存条件更新和跨进程锁仍生效。普通SQLite连接与内存库保持原行为。该机制没有提供多实例写入能力；本次同时修改了读投影与本地写准入，未做独立消融归因。

| 8并发观测 | 原基线 | 优化后 |
|---|---:|---:|
| 工作台订单列表P95 | 315.676ms | 53.664ms |
| 工作台订单列表P99 | 354.422ms | 67.740ms |
| 三请求结算流程P95 | 1041.018ms | 216.531ms |
| 三请求结算流程P99 | 1860.431ms | 226.912ms |
| 三请求流程吞吐 | 31.77流程/秒 | 48.96流程/秒 |

每次使用1000笔初始订单、120个虚构买家，1/4/8并发，每个负载120样本；主测量共1440个HTTP请求，错误0。每组另有12请求争抢3件库存，均3成功、9个预期409，业务一致性无异常。先前基线与新结果不是同载荷接口的严格微基准：列表改用了摘要，结算流程的三个请求保持不变。系统背景负载未完全隔离，结果是本机短时观测，不是峰值容量或生产SLO。

原始证据：

- [原始HTTP基线](evidence/benchmark-final-2026-11-25.json)、[优化后HTTP测量](evidence/benchmark-optimized-2026-11-25.json)。
- [优化前领域分解](evidence/query-profile-before-2026-11-25.json)、[优化后完整模式](evidence/query-profile-after-full-2026-11-25.json)、[优化后摘要模式](evidence/query-profile-after-summary-2026-11-25.json)。

重放时保留旧文件并选用新输出名：

```powershell
.venv/Scripts/python.exe scripts/commerce_benchmark.py --order-view summary --orders 1000 --samples 120 --concurrency 1,4,8 --output reports/benchmark-summary-new.json
```

## TLS与跨环境恢复

commerce_tls_smoke.py在临时库与独立服务中生成仅供测试的CA和证书，客户端显式信任该CA，保留证书链和主机名验证；系统信任库没有改变。不信任该CA的客户端被拒绝。实际验证Secure Cookie发送、账号登录/登出、CSRF拒绝、跨源拒绝、买家订单访问，以及operator不能确认支付/审核退款、owner可完成模拟流程。测试通过HTTP客户端完成，没有声称浏览器或真实域名已验证。[TLS原始结果](evidence/tls-verified-2026-11-25.json)。

commerce_cross_recovery.py在Windows创建最新完整业务快照，挂载只读备份到无外网Linux容器，恢复到新的临时文件，核对所有表行数、内容摘要及schema25；恢复后的买家登录、所有权、来源追踪及新模拟支付/退款均成功。这是同一物理机上的跨OS/隔离环境恢复，真实异机灾备仍未验证。[跨环境原始结果](evidence/cross-environment-recovery-2026-11-25.json)。

```powershell
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true --tmpfs /tmp:rw,noexec,nosuid,size=268435456 --entrypoint python crossborder-commerce:local scripts/commerce_tls_smoke.py
.venv/Scripts/python.exe scripts/commerce_cross_recovery.py --output reports/cross-recovery-new.json
```

## 已具体验证的发布候选

compose.release.yaml为独立的单实例TLS候选配置，要求证书、私钥、CA文件和证书DNS名称；使用独立命名卷、只读根文件系统、单worker、卖家鉴权、Secure Cookie和资源限制。默认仅绑定127.0.0.1，关闭代理头信任，直接在应用端提供TLS。健康检查连接本机端口并按配置名称验证证书，无需将证书名称解析到公网。

已用临时CA/证书实际启动到healthy，并通过protected预检；随后正常停止，临时私钥与测试证书目录已清理。没有公开端口、改DNS或安装系统根证书。[候选启动结果](evidence/release-candidate-2026-11-25.json)中的证书目录是已删除的临时测试路径，不是可复用生产证书。

真实目标确定后，先在目标环境提供以下本地路径及参数，再按顺序执行：

```powershell
$env:COMMERCE_TLS_CERTIFICATE='目标环境的服务证书PEM路径'
$env:COMMERCE_TLS_PRIVATE_KEY='目标环境的私钥PEM路径'
$env:COMMERCE_TLS_TRUST_CA='对应根CA或可信CA包PEM路径'
$env:COMMERCE_TLS_SERVER_NAME='证书覆盖的DNS名称'
$env:COMMERCE_TLS_HOST_PORT='8443'
docker compose -f compose.release.yaml config --quiet
docker compose -f compose.release.yaml up -d --no-build --wait
docker compose -f compose.release.yaml exec -T app python scripts/commerce_preflight.py --profile protected
```

本地演示仍为8027/8031。发布候选使用自己的卷，启动后需在目标卷执行迁移/数据准备及卖家Key配置；不能把另一套演示库的Key或商品当作已存在。正式证书私钥需对容器运行用户可读，不能提交到仓库。真实网络入口、浏览器Cookie与可信代理策略须按目标环境再次验证。

## 总体验收与未完成的外部事项

最终全量 **887 passed、1 xfailed、1 warning，48.59秒**，共888项；新增7项回归，覆盖批量兼容/摘要字段、过期索引既有覆盖、详情租户与角色边界、写准入的回滚/超时/中断/并发。已知died词表xfail及TestClient弃用提示仍保留。迁移往返检查通过，schema仍为25；复核确认原有过期索引已覆盖查询，未加入冗余迁移。

浏览器已验证摘要列表、展开完整订单来源、筛选空pending结果及恢复全部订单；多商品与原决策可追踪，error日志为空。宿主机与容器均更新，本机原项目副本范围之外没有发布或推送。

本地可演示交付范围已完成。继续公开发布、真实异机恢复与目标容量验收，需要确定实际服务器/平台、域名与证书管理方式、独立备份目的地及业务容量/SLO。这些外部条件尚未提供，不能以本机容器或假定云资源代替。公众服务还需按目标用途补齐账号验证/找回、运营监测及反滥用流程；本轮不将其写为已完成的生产能力。
