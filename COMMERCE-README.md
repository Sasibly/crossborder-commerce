# CrossBorder：选品与经营一体化演示系统

模拟付款现由买家在商城待支付订单下点击 `Pay … (simulated)`；卖家等待付款后处理发货。权限与实际验证见[买家支付修复](docs/BUYER-SIMULATED-PAYMENT.md)。

卖家前端现按八个业务分区显示：经营概览、商品与库存、订单与售后、评论分析、选品与成本、经营复盘、指标来源、设置与审计。默认首页提供高频快捷入口，切换模块保留表单；手机使用顶部业务导航。结构与入口映射见[卖家工作台信息架构](docs/SELLER-WORKSPACE-IA.md)。业务 API、状态机、角色权限和数据版本保持原规则。

订单信息首版完善见[订单详情说明](docs/SELLER-ORDER-DETAILS.md)：列表与详情展示成交快照、金额口径、模拟支付/物流和记录时间线；完整收货地址改为同店铺owner/operator单独授权读取，viewer保留脱敏详情访问。普通订单接口不再返回完整地址或订单访问令牌；交易状态机和数据版本不变。

## 当前交付入口（2026-11-26）

本轮1—5收尾已全部通过，见[统一验收证据](docs/evidence/local-acceptance-20261126.json)。实际统一运行：1051 passed、1个已知V1 xfail、1个弃用warning；五段均passed。商城原7件商品保留，完整流程新建的SIM测试商品已下架，预算仍20/20+20/20，无新增真实模型请求。

本版验收范围：本机8031、schema26、单商家US/USD、模拟供应商/支付/物流。日常使用[本机说明](docs/USER-GUIDE.zh-CN.md)，当前部署与备份命令见[部署说明](docs/LOCAL-DEPLOYMENT.md)。

```powershell
.\local-commerce.cmd deploy
.\accept-local.cmd
```

第一条部署并验证本机环境；第二条在已运行的8031实例上执行五段统一验收：固定数据/范围 → 全量测试、权限和缓存 → 六品类回归 → 六行订单完整买卖家流程及恢复重启 → 交付材料与指纹复查。成功退出0，任何失败退出非0，未执行项明确标记not_run；报告写入独立的 `reports/local-acceptance/时间戳-随机后缀/`，打开 `report.txt` 查看摘要，`report.json` 和同目录日志提供证据。

验收会创建明确标记SIM的6个商品、虚构买家及订单，测试后下架新商品，保留历史，不覆盖原商城商品或工作库；在线备份恢复到新文件。请在无人同时操作的本机演示实例运行，分析任务正在排队/运行时会拒绝进行重启验收。

| 品类 | 上线离线规则 | 本版支持范围 |
|---|---|---|
| 宠物饮水机 | V2 | 增强的合成数据演示，原20条语料负面标签F1=0.8750 |
| 无线充电器 | V1 | 有限质量基线，22条固定集F1=0.7805 |
| 空气净化器 | V1 | 有限质量基线，38条固定集F1=0.5185 |
| 咖啡机 | V1 | 有限质量基线，40条固定集F1=0.6000 |
| 电热水壶 | V1 | 有限质量基线，38条固定集F1=0.5517 |
| 扫地机器人 | V1 | 有限质量基线，42条固定集F1=0.4912 |

这些值只用于冻结输入上的回归，不是真实评论准确率或新数据效果承诺。六品类均支持模拟交易闭环；其他五类没有直接套用饮水机V2。本版生产标签仍为原10个通用标签，24个扩展标签和50单元AI预审候选保持草案，不计入模型已支持能力。两条证据不足项排除计分，人工批准数仍为0；用户提供的两批合成数据足以完成本轮演示验收，真实数据不作为此轮前置条件。

固定范围及文件指纹在 [local_demo_v1.json](data/acceptance/local_demo_v1.json)，新规则或数据要使用新版本验收依据，不能为了通过而修改旧值。统一入口不调用真实模型，现有百炼结果仍可读，原两份预算均已使用20/20。演示顺序和架构见[五分钟演示](docs/COMMERCE-DEMO.md)，可写入简历的边界见[项目材料](docs/COMMERCE-PORTFOLIO.md)。

## 阶段记录（历史说明，当前入口与范围以上节为准）

首次操作请阅读[本机使用说明](docs/USER-GUIDE.zh-CN.md)，包含启动、买卖家完整流程、商品调价、售后、模拟报价、备份和常见问题。

新增[百炼评论分析说明](docs/REVIEW-ANALYSIS-GUIDE.md)：工作台可运行独立评论分析任务、查看逐条抽取并从保存主题创建候选。已实际使用qwen3.5-flash分析10条宠物饮水机模拟评论，10次请求、10条通过结构与原文证据校验；交易继续模拟，授权总上限20次且持久计数。凭证仅在本机私有配置中保存。

评论分析性能已优化：最多3条并发、相同输入默认复用完整结果、运行进度轻量刷新。11月26日按新授权完成两轮真实测速，分别6.071秒、6.215秒，较旧串行中位耗时减少52.91%（小样本历史对比）。原授权20/20与追加授权20/20独立保留，累计40次；细节见说明中的“追加授权与真实测速”。

新增宠物饮水机合成演示评测：运行 `.\.venv\Scripts\python.exe scripts\review_demo_eval.py`，即可在本机生成逐条标签映射、未覆盖标注、情绪/证据检查及局部计分报告。使用固定离线规则，不消耗模型额度；10条合成评论和模拟标注不能支持真实准确率结论。用法与计分限制见评论分析说明中的“宠物饮水机合成演示评测”。

另有20条固定合成反例，可运行 `.\.venv\Scripts\python.exe scripts\review_holdout_eval.py`，检查原基线的否定句、同义词和缺失评分敏感性。原模型和标签未按此集调参，数据已对开发者可见，不称盲测；完整原标注及范围外内容均保留，细节见评论分析说明中的“固定合成反例回归集”。

宠物饮水机离线规则V2已部署到8031，修复分句、否定、归因纠正和同义表达，按独立版本复用结果；V1与旧报告保留，其他五个品类继续V1。运行 `.\.venv\Scripts\python.exe scripts\compare_offline_rules.py` 可查看冻结候选与V1对照；两个单集评测命令加 `--rules v2` 可评测新版。局部参考单元匹配提升不代表真实准确率100%，限制与验收见评论分析说明中的“离线规则V2修复与本机启用”。

标注规范准备工具已新增：`.\.venv\Scripts\python.exe scripts\review_annotation.py` 生成24标签草案、原文/原标注快照、待审清单、中文规范与未来评论输入模板。产品、耗材、服务、体验及不确定限定独立记录；原30条合成评论55个标注保持待审，不自动成为人工金标准，也不改变线上10标签或V2规则。操作和完整性校验见评论分析说明中的“宠物饮水机标注规范与待审草稿”。

全部55项AI预审也已完成，可运行 `.\.venv\Scripts\python.exe scripts\review_annotation_prereview.py` 复现独立工作副本、逐项审计和50单元合成参考候选。37项保留、14项修订、2项上下文、2项待人工核对；人工批准数仍为0，不改写原始标签或旧成绩。详见评论分析说明中的“全部55项标注的AI预审与候选参考集”。

**当前交付范围是本机部署与验证，已经完成。** 日常统一使用Docker的8031入口；运行 `local-commerce.cmd deploy` 可自动完成构建、启动、演示数据准备、HTTP业务验收、当前库备份恢复及重启验证。具体入口、账号和日常命令见 [本机部署说明](docs/LOCAL-DEPLOYMENT.md)。云服务器、域名与异机存储不作为本轮前置条件。

当前本地完整交付与外部部署边界见 [LOCAL-DELIVERY](docs/LOCAL-DELIVERY.md)：已连续完成订单摘要/批量查询、本地写事务准入、优化前后性能对比、证书验证下的HTTPS流程、Windows→Linux恢复及TLS发布候选。完整订单接口保持兼容，历史来源按需可查。

新增 [性能基线、恢复演练与预部署验证](docs/OPERATIONS-READINESS.md)：独立本机 HTTP 测量、覆盖最新快照的恢复工具、部署配置预检及无宿主端口的受保护 Compose 环境。模拟业务数据与实测技术指标分开标注，预检通过不代表公网已就绪。

既定的报价比较与利润压力分析已交付：两份本地模拟报价、每份五种情景、显式采用生成新决策，以及订单来源追踪。入口在工作台“模拟报价与利润压力比较”。见 [本轮验收](docs/PROFIT-COMPARISON-VALIDATION.md)、[五分钟演示与架构](docs/COMMERCE-DEMO.md)。

供应商默认全部本地模拟，业务指标独立记录来源，详见 [数据来源与模拟规范](docs/DATA-SOURCES-POLICY.md)。工作台可以创建模拟询价/报价/样品流程，并在决策中分别引用模拟报价和公开行业统计。公开退货率不会自动充当 SKU 实测值或售后成本。

现已支持按候选 SKU 保存指标场景：公开销售占比只能用于销售额参照；模拟单件退货概率可以显式计算并采用每件期望售后损失。场景保存输入假设与指标版本，决策和商品草稿继续保留来源快照。接口支持幂等重试，已有场景时禁止有损数据库降级。最新验证及下一步见 [场景测算验收](docs/METRIC-SCENARIOS-VALIDATION.md)。

当前连续迭代已推进到订单按笔计费、有界订单查询与业务一致性检查，见 [连续验收记录](docs/COMMERCE-CONTINUATION.md)。

工作台新增“订单支付费假设”配置（owner），结算保存当时策略。固定费用每笔只计一次；单件选品预测和旧订单保留历史口径。

```powershell
$env:PYTHONUTF8='1'
.venv/Scripts/python.exe scripts/commerce_reconcile.py --db data/commerce.sqlite3 --tenant local
```

以上为只读检查：正常退出 0，检出异常退出 2，不自动修复。订单筛选支持状态与创建时间，时间止不包含在内，经营汇总仍展示累计全量。

当前第三版已增加卖家角色、事务内审计与经营汇总，验收见 [docs/COMMERCE-V3-VALIDATION.md](docs/COMMERCE-V3-VALIDATION.md)。

## 卖家权限与审计

权限在 `AUTH_REQUIRED=true` 时依据 API Key 生效。现有未分配角色的 Key 保留 owner 权限；`commerce.cmd` 和本地 Compose 仍关闭鉴权，页面明确标记为本地演示。

| 角色 | 权限 |
|---|---|
| owner | 所有现有卖家管理操作，包括退款审核及损失登记 |
| operator | 日常选品、商品、库存、发货和订单完成；不能模拟确认收款、退款、审核退款或登记损失 |
| viewer | 读取接口；所有受原 API Key 保护的写接口均拒绝，包括旧任务接口 |

先迁移数据库，再通过本机 CLI 创建指定角色的 Key（明文仅显示一次）：

```powershell
.venv/Scripts/python.exe scripts/db.py up
.venv/Scripts/python.exe scripts/keys.py --db data/commerce.sqlite3 create --tenant local --label operations --role operator
.venv/Scripts/python.exe scripts/keys.py --db data/commerce.sqlite3 create --tenant local --label readonly --role viewer
```

Key 的角色目前由本机运维管理，不提供网页提升权限功能。普通读取权限包含本租户成本和收货资料，并非脱敏分析员角色。工作台按照角色禁用按钮，真正权限由服务端验证。`/metrics` 为只读鉴权入口。

审计覆盖候选创建、决策、商品草稿/上架、库存与订单状态、买家退款申请、审核和损失记录。审计与对应业务写入同事务提交；审计写失败会回滚业务。记录只含对象 ID、动作和必要数值，不存请求正文、密码、地址或退款理由。DB 内保存精确执行者引用，API 只展示 Key 前缀或买家短 ID；升级前的历史操作不补造身份。

`GET /v1/commerce/audit?after=0&limit=50` 按游标分页；UPDATE/DELETE 被数据库触发器拒绝，但这不代表可以抵御拥有数据库文件控制权的管理员。

经营汇总区分累计模拟收款、整单退款、留存收款和贡献。成本缺失时完整贡献合计为 null，另列已知小计及缺失订单数，避免把未知利润当成零。它按当前订单状态汇总，不是期间财务报表。

评论证据 → 候选 SKU → 独立站成本决策 → 商品草稿 → 模拟订单与履约 → 预测偏差复盘。

原选品系统说明保留在 README.md，修订后的范围与验收见 docs/COMMERCE-PLAN.md。

## 备用开发入口（不纳入日常8031验收）

```powershell
cd D:/Codex_Projects/crossborder-commerce
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./commerce.cmd
```

打开 http://127.0.0.1:8027/workbench ，买家商城为 http://127.0.0.1:8027/shop 。可用 `./commerce.cmd 8030` 更换端口。脚本强制 mock、local 租户、关闭本地 API Key 校验，数据库使用 data/commerce.sqlite3，仅监听本机。不要将这个演示启动方式用于公网。

本目录若已存在 .venv，无需重复安装。

## 第二版：购物车、买家与售后

第二版已加入买家账号、US 地址、服务端购物车、多商品订单、退款审核、退款净损失登记和自动库存清理。原立即购买 API 保留兼容；商城页面使用买家登录及购物车结算。

初始化六个品类、共七个虚构演示商品与买家（宠物饮水机两个，其余品类各一个；可重复执行，不重置已有商品、密码或库存）。分析品类列表不等于已上架商品列表，新商品仍须经过候选 SKU → 独立站决策 → 商品草稿 → 入库并上架。调价可显式替换旧商品上架版本，历史订单保持原价；也可单独下架。最新买卖家一致性修复与验收见[验收记录](docs/CONSISTENCY-FIX-VALIDATION.md)：

```powershell
$env:PYTHONUTF8='1'
.venv/Scripts/python.exe scripts/seed_commerce.py
./commerce.cmd
```

演示邮箱：`demo-buyer@example.test`；演示密码：`demo-pass-local-2026`。仅供本地虚构演示，正式环境不要创建该账号。也可以在商城中用虚构邮箱创建自己的测试账号；目前没有邮箱验证、找回密码或邮件发送功能。

新演示路径：登录 → 两件不同商品加入购物车 → 保存虚构 US 地址 → 合并下单 → 买家模拟支付 → 卖家发货并完成 → 买家提交整单退款 → 卖家审核 → 填写退款净损失 → 复盘中查看负贡献。退货物流和部分退款仍未实现。

后台每 30 秒检查超时订单，启动时立即检查一次。可用 `COMMERCE_EXPIRY_INTERVAL` 配置间隔（1–3600 秒）。买家口令采用带独立盐的 scrypt；Cookie 为 HttpOnly/SameSite=Lax，写操作需要 CSRF Token。上线到 HTTPS 环境前配置 `COMMERCE_SECURE_COOKIES=true`。登录/注册和结算有限流；没有启用邮件身份验证、分布式防滥用或员工角色体系。

第二版验收结果见 [docs/COMMERCE-V2-VALIDATION.md](docs/COMMERCE-V2-VALIDATION.md)。

## 五分钟手动演示

1. 在工作台选择 pet_fountain，分析评论，选择一个机会，创建候选 SKU。
2. 采用预填的演示费用，先保持风险“待核查”，保存一次 NEED_MORE_INFO 决策。
3. 选择“演示案例：已检查”，保存新版本，得到 GO；展开查看历史证据与费用。
4. 点击生成草稿，入库 10 件，上架。再次点同一决策生成草稿不会复制商品。
5. 打开买家商城，提交一件模拟订单。不会收取真实资金。
6. 买家在商城 Your orders 点击 Pay … (simulated)，再返回卖家工作台刷新；把实际物流费改为 550 分后发货，标记完成。
7. 复盘显示预测 980 分、记录贡献利润 930 分、差额 -50 分；订单关联原决策。
8. 可继续模拟退款；登记完整的退款净损失前，复盘显示待补全。第二版支持填写货物、物流、支付和其他净损失后，按负贡献展示。

## 在线备份与恢复演练

```powershell
.venv/Scripts/python.exe scripts/commerce_backup.py backup data/commerce.sqlite3 backups/manual.sqlite3
.venv/Scripts/python.exe scripts/commerce_backup.py restore backups/manual.sqlite3 backups/restored.sqlite3
```

工具使用 SQLite 在线备份 API，包含已提交 WAL 数据，并检查数据库和外键完整性。目标已存在时拒绝覆盖。恢复演练写入新文件；替换工作库前先停止服务，保留旧库及 WAL/SHM，验证新库后再切换 `DB_PATH`。备份含买家资料和会话信息，应按敏感文件保存；不要提交到代码仓库。

迁移 0019 会回填旧订单明细。新买家或多商品订单产生后，降级至 0018 会被明确拒绝，防止丢失订单明细与所有权。

## Docker 本地部署

```powershell
docker compose build
docker compose up -d --no-build --wait
docker compose exec -T app python scripts/seed_commerce.py
.venv/Scripts/python.exe scripts/commerce_smoke.py --base-url http://127.0.0.1:8031
```

如果 Docker Hub 不可达，可使用已实测的 Microsoft 官方基础镜像：

```powershell
docker compose build --build-arg PYTHON_IMAGE=mcr.microsoft.com/devcontainers/python:3.13
```

Compose 仅映射本机 `8031` 端口，使用命名卷持久化数据库和演示样本；卷与宿主机 `data/commerce.sqlite3` 相互独立。`docker compose stop` 停止容器后保留数据，重新 `up` 可继续使用。不要执行带 `--volumes` 的清理来代替正常停止。

该 Compose 是本地演示配置，卖家 API 鉴权关闭，不能直接改为公网绑定。镜像自身默认开启原 API Key 鉴权；需要时可用 `scripts/keys.py create --tenant local` 创建 Key，并在卖家工作台输入。公网部署还需 HTTPS、Secure Cookie、账户验证、角色与数据治理。

HTTP 烟测只允许本机且 `/health` 为 mock 的实例，会创建虚构买家和两商品订单，完成幂等支付、退款审核、损失登记及库存恢复检查，不会发送真实资金。

## 验证

```powershell
./check-commerce.cmd
```

脚本启用 PYTHONUTF8=1，避免 Windows GBK 解码 UTF-8 CLI 输出。演示脚本使用临时数据库，不污染工作区：

```powershell
$env:PYTHONUTF8='1'
.venv/Scripts/python.exe scripts/commerce_demo.py
.venv/Scripts/python.exe -m pytest tests/test_commerce.py -ra
```

新增测试验证金额、未知成本、渠道隔离、决策快照、草稿幂等、下单幂等、支付金额与去重、库存并发、超时释放、退款规则、订单凭证和完整 HTTP 链路。基于文件数据库的并发测试使用 12 个请求争抢 3 件库存。

默认价格 $30，采购成本 ¥70，汇率 7，物流 $5，支付费 $1.20，售后 $1，获客 $3：单件预计贡献利润为 $9.80。新订单按整笔金额及固定费计算，旧单和单件选品预测保留原始假设；所有费用仍是演示规则，不代表真实服务商账单。

生产准备和功能扩展的未完成项见规划文档，演示数据不能用于证明真实经营或模型准确率。
