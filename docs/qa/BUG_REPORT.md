# 缺陷报告 / 独立 Codex 修复交接

更新时间：2026-11-27（Asia/Shanghai）。本轮已执行缺陷修复与隔离验证；原始独立测试证据保留在下文，当前状态以索引及各项修复记录为准。

## 独立回归结论（2026-11-27，当前状态优先）

本轮是测试/验收会话，未修改业务代码、未部署、未调用真实模型。已逐项读取14个FIXED的原复现/验收标准及修复实现。结果：**13 VERIFIED、1 REOPENED（BUG-005）、1 BLOCKED（BUG-013）**；未发现需要新编号的独立缺陷，新增复现属于原BUG-005。下方修复会话的FIXED统计和原始实际结果作为历史保留，不代表最新状态。

### 独立全量回归

重跑全部测试：**1094 passed、1 known xfailed、1 warning，75.65秒，退出0**。环境沿用mock/hash、空live key/base URL、禁用配置、独立临时库，schema27。命令：
`python -m pytest -o addopts= -q -ra --tb=short -p no:cacheprovider --basetemp D:/Codex_Projects/tmp/independent-20261127-all --junitxml D:/Codex_Projects/tmp/independent-20261127-all.xml`（实际解释器为项目.venv/Scripts/python.exe）。
JUnit已归档至`reports/independent-regression-20261127/pytest.xml`。V1 xfail与Starlette/httpx warning仍是原有问题，未被本轮忽略或消除。

### 独立浏览器回归

本轮自行启动`scripts/qa_browser_server.py`在loopback18031测试当前源码（临时qa-browser数据库，不是部署8031）；运行`scripts/qa_repairs_browser_check.mjs`，新证据目录`reports/independent-regression-20261127/browser/`：**12组通过、异常0、POST0**。包括8视图、按需读取、缓存保留输入、复盘GET故障隔离与恢复、390px。该测试数据库脚本可能复用同名QA库，未声称空库。测试结束停止本轮服务。未对8031部署执行变更/迁移。

### 独立补充诊断

新增诊断脚本仅存证据目录，不改业务/既有测试：
- `reproduce_bug005.py`：确定性复现旧analytics强制刷新覆盖新结果，退出0表示**缺陷成功复现**，不是通过验收。使用现有VM harness，替换moduleStatus及未加载的refreshReviewAnalyses为无副作用桩，loadSellerReview和loadSellerModule使用真实源码。
- `supplemental_checks.py`：按ID历史两前端处理函数、只读退款成本渲染及三角色finance谓词断言通过。
- 开发诊断最初因VM缺少外部脚本函数/DOM方法未到请求阶段的断言不作为产品失败证据；补齐必要桩后才得到上述有效复现。

### 验证范围及限制

VERIFIED针对**当前源码、隔离API/VM及上述浏览器范围**，不是8031部署验收，也不声称全部交易写流程在浏览器手工实点。原生文件导入全组合、真实用户Key实点、部署库写操作仍未执行。各项具体依据/限制见其“独立回归”记录。BUG-013未验证修复，因为仍BLOCKED且V1冻结；未虚报通过。Git仍非仓库，无法记录branch/HEAD，归档source-hashes.json用于源码基线。原始缺陷描述、修复记录及旧测试保留。

## 本轮修复结果（2026-11-27，历史记录）

- 14项FIXED，等待另一独立会话回归；BUG-013为BLOCKED，V1规则受明确冻结约束，未擅改规则、历史缓存或xfail。没有项目标为VERIFIED。
- 当前四个前端源码修复前SHA256均匹配报告基线；Git仍不可用。修复前副本及哈希位于`reports/bugfix-20261127/baseline/`及`baseline-hashes.json`。本轮修改未覆盖其他会话变更。
- 用户已明确批准BUG-004的`docs/MODULE-LOADING-PROPOSAL.md`方案并要求不部署。已完成源码修改及隔离验证；8031本机部署实例未修改。
- P1修复新增schema27卖家原子去重表，隔离测试覆盖并发、回放冲突及事务回滚；本机业务库保持原状。冻结`local_demo_v1.json`未改，验收器显式核验新增迁移SHA256及运行时schema27，不放宽冻结数据、标签和网络约束。
- 全量命令（使用下文禁用live环境）：`.venv/Scripts/python.exe -m pytest -o addopts= -q --tb=short -p no:cacheprovider --basetemp D:/Codex_Projects/tmp/qa-final-all --junitxml D:/Codex_Projects/tmp/qa-final-all.xml`。结果：**1094 passed、1 known xfailed、1 warning，73.55秒，退出0**。完整JUnit复制到`reports/bugfix-20261127/pytest-final.xml`。
- 针对命令：同样pytest参数，选择`tests/test_qa_repairs_ui.py tests/test_qa_repairs_business.py tests/test_buyer_payment_ui.py tests/test_local_acceptance.py tests/test_review_analysis.py tests/test_seller_category_recovery.py tests/test_migrations.py`，**57 passed**；最终小步反馈及标签结构调整后，UI测试再跑**8 passed**。
- 真实Chrome：`node scripts/qa_repairs_browser_check.mjs`，连接`qa_browser_server.py`的一次性loopback18031服务，**12组通过、0浏览器异常、0业务POST**；包含八分区、按需读取、缓存、草稿、注入失败与恢复及390px布局。证据和截图位于`reports/bugfix-20261127/browser/`。不声称执行完整浏览器写交易链或独立回归。
- 初次全量发现的4项失败已解决：VM补标准AbortController/定时器能力；schema26评论不可降级测试固定跨25而非LATEST-1；冻结验收器显式验证schema27扩展；旧身份失败读不能覆盖新品类状态。未降低断言或忽略失败。
- 两批真实模型预算保持原状，本轮没有新增外部模型请求。无Git commit、push或部署。OPT项未扩大处理。

## 1. 环境与基线

- 项目根：`D:/Codex_Projects/crossborder-commerce`。下文未带前缀的业务源码均位于 `src/xborder_insight/`；tests、docs、scripts路径相对项目根。函数未注明类时为模块/页面全局函数，无所属类。行号为整理时参考，后续按符号定位。
- Git分支/提交：**无法获取**。在项目根执行 `git branch --show-current`、`git rev-parse HEAD` 均报 `fatal: not a git repository (or any of the parent directories): .git`。不能声称工作区干净或编造HEAD。
- Windows/PowerShell；Python 3.13.14，Node 24.19.0，FastAPI 0.165.0，Starlette 1.10.0，httpx 0.28.1，pytest 9.2.0；Chrome版本未记录，使用已安装Chrome独立headless配置。
- 目标 `http://127.0.0.1:8031`，项目约定schema26、本地mock交易。/shop实际使用commerce_shop_v2.html，旧commerce_shop.html不是当前入口；/workbench使用commerce_workbench.html、commerce_seller.js、review_analysis.js。
- 修复前读根AGENTS.md：供应商/支付/履约保持simulation，保存历史快照与指标来源；两批live模型预算已耗尽，共40次，禁止新增调用、重置预算或外传导入评论。冻结V1/评估数据/反例不得擅改。
- 读取重构先读 `docs/MODULE-LOADING-PROPOSAL.md` 与AGENTS：既往自动审批两次拒绝refresh/init重构。本次报告不授予业务修复权限；后续按当时明确授权和审批要求执行，不得绕过拒绝。
- 本会话真实浏览器业务写请求0、模型调用0。支付提示部分用函数替身验证，不等于真实浏览器下单支付；完整写链主要由隔离接口/状态机测试支持。
- 源码SHA-256：commerce_workbench.html=`24cfd4c46b0d273bef4975fd3598cbb4e05e31f4b69002ad073ce84dcf739945`；commerce_seller.js=`a435a819538d750f011ee3efc7adb555ed01ee9c11bd285e95406a40a44b8fa0`；commerce_shop_v2.html=`96a9ef15a4ee4261a0257dbd018b388a2fedb2283aeb970afd41d9cc83bdf885`；review_analysis.js=`ee505cb70ec9b72852a197510f829613c7105c656269b194b246c4dee4030ff2`。这是局部定位基线，不是全项目版本声明。

## 2. 已执行验证及证据

| 编号 | 实际结果 | 证据位置与限制 |
|---|---|---|
| E1 | 全量pytest：1081 passed、1 known xfailed、1 warning；69.38秒，退出0 | `D:/Codex_Projects/tmp/frontend-audit-20261126-tests.xml`：1082用例、0失败/错误、1 skipped（xfail）；临时文件可能清理，摘要已内嵌 |
| E2 | 真实Chrome：18组通过、119请求、非预期控制台错误0 | `reports/frontend-audit-20261126-browser/browser-check.json`及同目录截图；业务写/模型调用均0，匿名account/me的401是预期 |
| E3 | 3段Node VM诊断执行成功；两次mutate发2次api；刷新失败被成功覆盖 | 使用`tests/test_identity_and_busy_ui.py`的execute/HARNESS，从stdin临时执行，退出0、输出“3 diagnostic scripts completed”；未保存独立测试文件。第三段仅观察读取候选时机，没有完成乱序复现 |
| E4 | 静态AST提取5个API文件79个路由声明及hash/事件 | `D:/Codex_Projects/tmp/frontend-audit-inventory.json`；原功能映射`D:/Codex_Projects/tmp/frontend-loop-audit-20261126.md`。临时文件不是理解本报告的必要依赖，79含HTML/资产/通用接口，不是业务功能数 |
| E5 | 首次证据输出权限失败，恢复后采用E1/E2 | 见ENV-001，不算业务用例失败 |

测试环境变量：PYTHONUTF8=1，TEMP=TMP=D:/Codex_Projects/tmp，RUN_MODE=mock，EMBEDDING_PROVIDER=hash；REVIEW_LLM_API_KEY/REVIEW_LLM_BASE_URL置空，REVIEW_CONFIG_PATH指向不存在的禁用配置。tests/conftest.py使用内存/临时文件库，不测试本机业务库写操作。

E1已有命令（修复回归时才再执行；设置上述变量、为basetemp取新唯一目录）：

```powershell
.venv/Scripts/python.exe -m pytest -o addopts= -q -ra --tb=short -p no:cacheprovider --basetemp D:/Codex_Projects/tmp/frontend-audit-20261126-r2 --junitxml D:/Codex_Projects/tmp/frontend-audit-20261126-tests.xml
```

E2已有命令：设置SELLER_BROWSER_REPORT_DIR=reports/frontend-audit-20261126-browser后运行 `node scripts/seller_workspace_browser_check.mjs`。未开启可写业务库的SELLER_BROWSER_CHECK_BUYER_PAYMENT分支。

### 自动化测试覆盖

买家账户/CSRF/地址/购物车/结算/支付/订单/退款；卖家商品/库存/订单状态/财务权限/快照/审计/供应商/场景/比较/评论任务、身份/忙状态等；全套还覆盖分析、任务与运维相关模块。套件通过不代表异常前端路径已覆盖。

### 实际浏览器覆盖

1440×1000与390×844；8视图overview/products/orders/insights/sourcing/analytics/sources/settings；正常导航、前进后退、代表性深链接、筛选、弹窗焦点/Escape、输入保留、品类失败恢复、订单详情/显式收货读取、身份隔离及支付提示。未发现主交易路径fetch地址/主要字段名确定性错配，未发现hash切换整体丢失事件。

### 未实际完成的验证

完整浏览器业务写链、真实角色Key全部交互、原生CSV/JSONL各异常文件、逐模块故障注入、超量历史、超时订单、乱序竞态。各项下面给出待执行复现方案，不冒充实测。

## 3. 缺陷索引

分类：已确认（脚本/测试）、已确认（代码审查）、疑似（待复现）、优化建议/规则待定。无本会话已发现P0；按P1→P3排列，优先级是交接建议。

| 编号 | 级别 | 标题 | 当前状态 |
|---|---|---|---|
| BUG-001 | P1 | 卖家变更可重复提交 | VERIFIED |
| BUG-002 | P2 | 写后刷新失败被成功提示覆盖 | VERIFIED |
| BUG-003 | P2 | operator可点击后端禁止的财务按钮 | VERIFIED |
| BUG-004 | P2 | 卖家全局读取耦合且缺模块恢复 | VERIFIED |
| BUG-005 | P2 | 同身份并发读取可能覆盖新状态或重复分页 | REOPENED |
| BUG-006 | P2 | 超时清理缺页面入口 | VERIFIED |
| BUG-007 | P2 | 历史分析和比较只能访问最近记录 | VERIFIED |
| BUG-008 | P2 | 切Key后残留旧一致性检查结果 | VERIFIED |
| BUG-009 | P2 | 买家会话读取故障被当作未登录 | VERIFIED |
| BUG-010 | P2 | 买家订单刷新被商品或购物车故障阻断 | VERIFIED |
| BUG-011 | P2 | 卖家首次数据集失败后的重试不完整 | VERIFIED |
| BUG-012 | P2 | 评论进度轮询遇单次错误即停止 | VERIFIED |
| BUG-013 | P2 | V1将高星隐性故障识别为正面 | BLOCKED |
| BUG-014 | P3 | 请求无超时，悬挂时可能长期锁按钮 | VERIFIED |
| BUG-015 | P3 | 已登记退款成本缺明细核对界面 | VERIFIED |

## 4. 缺陷详情

### BUG-001：卖家变更可重复提交

- **严重程度**：P1。
- **所属模块**：卖家商品/候选/决策/供应商。
- **当前状态/证据级别**：VERIFIED。
- **详细描述/触发条件**：同一请求未完成时再次点击；非幂等入库、创建可能重复生效。不能断言所有订单状态转换都会重复写。
- **完整复现步骤**：隔离mock库准备商品；限速后在 #products/product-list 打开管理弹窗；连续两次点确认入库；检查Network和库存流水。该实点方案未执行。已执行VM：阻塞api，连续调用两次 mutate('/products/p/stock',{quantity:1})，断言calls===2，再释放返回。
- **预期结果**：同一未完成操作仅提交一次。
- **实际结果**：E3收到2次api调用；尚未用本机业务库量化重复库存/金额。
- **文件/类/方法/位置**：commerce_workbench.html:64-71 api/mutate/createCandidate/assumptions.onsubmit；commerce_seller.js:newSupplierCase/supplierTransition；commerce_api.py:stock/candidates/decisions/draft路由；procurement_api.py:74 new。
- **错误日志/测试证据/原因**：E3断言通过；前端无操作锁，通用mutate无幂等头。后端需去重的写操作须逐项审查，不能仅添加header。
- **建议修复方案**：按身份代次+资源+操作锁定；非幂等创建/入库增加稳定请求标识和服务端去重；未知写结果不自动换key重放。
- **修复验收标准**：双击一次业务效果；超时重试不重复；DOM刷新保持锁；切Key后旧finally不能释放新锁；不同资源可独立操作。
- **修复记录（2026-11-27）**：根因及方案见前次记录及本次源码：身份/操作锁覆盖写后刷新，写请求合并与未知结果复用幂等键；新增schema27去重表，候选/决策/库存/供应商创建原子保存结果。修改commerce_workbench.html、commerce_seller.js、review_analysis.js、commerce_api.py、procurement_api.py、seller_requests.py及m0027迁移注册。验证：pytest tests/test_qa_repairs_ui.py tests/test_qa_repairs_business.py（包含于qa-target-final.xml的57 passed）；4线程同key入库仅+2、冲突409、写后失败回滚、viewer403、UI重入及未知结果复用key通过。风险：旧工具未发幂等头时保留兼容行为；去重跨页面刷新需调用方保留原key；不宣称独立回归通过。
- **独立回归（2026-11-27）**：VERIFIED｜全量重跑 test_seller_write_reentry_refresh_failure_and_identity_lock、test_stock_receipt_parallel_replay_conflict_and_atomic_failure、test_seller_http_receipts_permissions通过；确认双击/写后读取锁、身份切换锁、4线程原子去重、冲突409与回滚。未执行部署8031写操作。


### BUG-002：写后刷新失败被成功提示覆盖

- **严重程度**：P2。
- **所属模块**：卖家操作反馈。
- **当前状态/证据级别**：VERIFIED。
- **详细描述/触发条件**：写成功、后续读取失败被catch吞掉，外层仍统一报成功，界面可能陈旧。
- **完整复现步骤**：VM加载卖家脚本；替换api=async()=>({})、refresh=async()=>notify('读取失败')，模拟真实refresh吞错返回；await mutate；读取message。此VM已执行。浏览器在隔离库阻断写后的GET再提交入库，尚未执行。
- **预期结果**：区分写失败、写成功但页面刷新失败、写结果未知，提示只重试读取。
- **实际结果**：E3最终message为“操作已完成”，覆盖“读取失败”。
- **文件/类/方法/位置**：commerce_workbench.html:65,72-77 mutate/refresh；commerce_seller.js:loadOrders、146 loadAudit。
- **错误日志/测试证据/原因**：E3；catch仅notify，不传播失败/结构化状态；外层无条件成功提示。
- **建议修复方案**：返回结构化读写结果；已保存但刷新失败单独提示，保留可用模块，避免诱导重复写。
- **修复验收标准**：各失败分支提示正确且不被覆盖；读重试不重复变更；与BUG-004联测。
- **修复记录（2026-11-27）**：根因：refresh吞错及mutate无条件成功提示。修改commerce_workbench.html/commerce_seller.js：分区读取返回成功状态，已保存但刷新失败单独提示，订单及审计读取传播失败。验证：tests/test_qa_repairs_ui.py写成功/刷新失败断言通过（57项针对回归），真实Chrome模块失败隔离通过。遗留：等待独立回归。
- **独立回归（2026-11-27）**：VERIFIED｜test_seller_write_reentry_refresh_failure_and_identity_lock确认刷新false后提示“已保存/读取失败”；源码refresh状态返回与mutate分支复核；Chrome模块失败恢复通过。


### BUG-003：operator可点击后端禁止的财务按钮

- **严重程度**：P2。
- **所属模块**：订单退款/售后权限。
- **当前状态/证据级别**：VERIFIED。
- **详细描述/触发条件**：operator访问已付订单或待审核退款时，两处按钮漏标finance，页面可点、接口禁止；不是后端越权。
- **完整复现步骤**：隔离库配置operator Key及已付订单/待审申请；加载 #orders；检查主动整单退款及拒绝申请按钮；输入说明提交；检查403。该角色实点方案未执行。
- **预期结果**：operator财务入口禁用并说明权限；owner可操作。
- **实际结果**：源码默认operate允许operator；后端financial判断抛403 Forbidden，文案“此操作需要 owner 角色”。
- **文件/类/方法/位置**：commerce_seller.js:25 renderOrderActions、74 refreshRefunds、setRoleButtons/sellerCan；security/roles.py:23 authorize。
- **错误日志/测试证据/原因**：两按钮缺 data-seller-permission="finance"；未标按钮默认operate。E2正常角色元数据检查通过不能证明这两入口正确。
- **建议修复方案**：补财务元数据；动态渲染后统一判权，保留服务端校验，不按文案判权。
- **修复验收标准**：owner/operator/viewer三角色及刷新后的按钮一致；403边界不退化。
- **修复记录（2026-11-27）**：根因：两财务按钮漏finance元数据。commerce_seller.js补齐主动退款及拒绝申请元数据。测试：tests/test_qa_repairs_ui.py及test_commerce_access.py验证元数据与服务端owner/operator/viewer边界；前31项及最终57项通过。遗留：等待独立三角色浏览器回归。
- **独立回归（2026-11-27）**：VERIFIED｜test_seller_finance_metadata_and_integrity_scrub、test_commerce_access.py均通过；独立VM另验owner/operator/viewer的finance谓词及财务元数据。未配置真实浏览器三套Key，但隔离权限接口及实际生成HTML均覆盖。


### BUG-004：卖家全局读取耦合且缺模块恢复

- **严重程度**：P2。
- **所属模块**：卖家各hash视图。
- **当前状态/证据级别**：VERIFIED。
- **详细描述/触发条件**：refresh串联商品、订单、复盘、售后、来源、配置、汇总、审计、任务；中间异常可阻断后续模块，多数模块缺独立loading/error/retry。已有品类加载状态应保留。
- **完整复现步骤**：打开工作台；阻断GET /v1/commerce/review后刷新；检查后续售后/汇总/审计；切hash观察恢复；恢复网络尝试本视图重试。故障注入尚未执行。
- **预期结果**：单模块失败不阻断其他模块，当前模块可见错误并能独立重试。
- **实际结果**：源码顺序await遇错跳catch；hash只切DOM，无独立恢复。E2只验证正常导航及品类错误恢复。
- **文件/类/方法/位置**：commerce_workbench.html:72-78 refresh/init；commerce_seller.js:155 refreshManagement、194 refreshSources、renderSellerWorkspace/initSellerWorkspace。
- **错误日志/测试证据/原因**：源码顺序await/共享catch；BUG-002反馈覆盖是关联但独立可验收问题。
- **建议修复方案**：独立模块状态、请求合并/失效和重试；保留表单DOM与身份保护，导航不提交分析任务。先读 docs/MODULE-LOADING-PROPOSAL.md 及AGENTS审批约束。
- **修复验收标准**：逐模块500/网络失败时其他模块可用；失败不标loaded；可恢复；hash保留输入；BUG-002正确；E2不退化。
- **修复记录（2026-11-27）**：用户批准MODULE-LOADING-PROPOSAL方案，不部署。根因：全局顺序读取失败级联。commerce_workbench.html/commerce_seller.js增加按分区读取、状态缓存、请求合并、独立失败/重试、身份及加载代次失效，保留表单DOM；不触发新模型任务。验证：tests/test_qa_repairs_ui.py模块故障/合并/恢复通过；node scripts/qa_repairs_browser_check.mjs在隔离18031的真实Chrome12组通过，含8视图、缓存导航、草稿、注入失败与恢复、390宽布局，0业务POST/0异常。风险：本机8031未部署；等待独立回归。
- **独立回归（2026-11-27）**：VERIFIED｜test_seller_modules_isolate_errors_retry_and_dataset_recovery通过；独立Chrome12组涵盖8分区、按需读取、缓存、故障隔离/恢复和390px布局。并发强制读取遗留由BUG-005独立REOPENED跟踪，不视为模块读取功能已覆盖所有竞态。


### BUG-005：同身份并发读取可能覆盖新状态或重复分页

- **严重程度**：P2。
- **所属模块**：审计/场景/比较/来源/全局刷新。
- **当前状态/证据级别**：REOPENED。
- **详细描述/触发条件**：同身份连刷、同游标更多连点、候选A→B→A；仅身份和候选值相等不足以证明请求最新。
- **完整复现步骤**：VM或拦截网络保留两次同模块GET；先返回新数据再返回旧数据，观察DOM；并发loadAudit(true)同游标返回同页；场景/比较执行A→B→A。以上未完整执行；E3第三段仅观察refreshSources网络后读取当前候选。
- **预期结果**：只允许最新请求渲染；分页不重入、不重复。
- **实际结果**：源码缺统一同身份请求序号；真实覆盖/重复结果尚未验证，不能称发生了串写。
- **文件/类/方法/位置**：commerce_seller.js:146 loadAudit、194 refreshSources、243 loadMetricScenarios、281 loadProfitComparisons；commerce_workbench.html:72 refresh；对照loadOrders已有orderQueryGeneration。
- **错误日志/测试证据/原因**：E4代码审查；E3最后一段不是乱序缺陷复现。原因待失败用例确认。
- **建议修复方案**：先补可重复失败的乱序用例；捕获候选/请求序号并核验，分页锁/按ID去重，必要时取消旧读，保留身份代次。
- **修复验收标准**：新结果不回退、分页无重复、A→B→A不混用；先证实再修，不将理论风险写为实测事故。
- **修复记录（2026-11-27）**：先复现：tests/test_qa_repairs_ui.py的A→B→A场景旧响应覆盖及审计并发重复游标两项均失败。根因：仅核验候选值且append无合并。commerce_seller.js为来源/场景/比较/审计增加请求代次和身份核验，审计append合并；commerce_workbench.html共享状态核验加载代次。修后两项通过，含于57项针对回归。风险：等待独立网络乱序回归。
- **独立回归（2026-11-27）**：REOPENED｜独立新增复现：loadSellerModule('analytics',true)两次，后请求先返回[]，旧请求后返回old-order行，最终review含old-orde；新结果被覆盖。既有场景A→B→A和审计append测试仍通过，仅修复部分竞态。


### BUG-006：超时清理缺页面入口

- **严重程度**：P2。
- **所属模块**：待支付订单/库存。
- **当前状态/证据级别**：VERIFIED。
- **详细描述/触发条件**：超过15分钟但无新结算或显式清理时，订单仍可pending并占库存；支付提示执行清理，页面无批量清理入口。逐单取消仍可恢复。
- **完整复现步骤**：隔离库下单；仅测试库将expires_at设过去或等待到期；只刷新商品/订单；点击支付；查库存及清理入口。未执行本轮真实到期实验。
- **预期结果**：既有超时清理可从页面执行或有明确可靠自动策略，文案与真实行为一致。
- **实际结果**：commerce.py只在新结算或POST清理调用expire；读取不清理；支付抛“订单已超时，请执行超时清理”。
- **文件/类/方法/位置**：commerce.py:307 expire、332 checkout_items、370-380 transition；commerce_api.py:200 expire路由；commerce_shop_v2.html:118-140；commerce_seller.js:renderOrderActions。
- **错误日志/测试证据/原因**：E4调用关系及入口检查；未记录到期实点证据。
- **建议修复方案**：受控卖家清理入口并刷新库存/订单，或按授权设计定时清理；买家显示到期时间/取消路径；GET不暗中写库。
- **修复验收标准**：到期释放恰好一次、未到期不取消、支付不能越过到期校验；用户可由页面完成恢复。
- **修复记录（2026-11-27）**：核验原始相同哈希源码发现释放超时库存按钮与POST/expire已存在，报告入口缺失结论不成立；实际问题为后台每30秒自动清理文案不实，commerce_workbench.html改成显式清理/后续结算触发。tests/test_qa_repairs_business.py验证超时支付拒绝、到期释放恰好一次、未到期不取消；57项针对回归通过。保留GET只读，无自动定时任务新增；待独立回归。
- **独立回归（2026-11-27）**：VERIFIED｜test_expiry_releases_once_keeps_unexpired_and_rejects_payment通过；复核workbench现有POST /expire按钮→mutate链、mock到期提示。验证释放一次/保留未到期/拒绝到期支付；未在部署库等待15分钟或执行清理。


### BUG-007：历史分析和比较只能访问最近记录

- **严重程度**：P2。
- **所属模块**：评论任务/报价比较历史。
- **当前状态/证据级别**：VERIFIED。
- **详细描述/触发条件**：分析>30条或同候选比较>20份时，旧快照还在库但页面无法找回；缺分页及按ID入口。
- **完整复现步骤**：隔离库生成31个离线任务、同候选21份比较，禁止live；刷新两历史下拉；找最早记录；对比按ID读比较详情。批量实点未执行。
- **预期结果**：所有合法历史均可只读访问，不覆盖来源版本。
- **实际结果**：SQL LIMIT30/20；页面无后续分页；比较虽有按ID接口但无页面入口。
- **文件/类/方法/位置**：review_analysis_api.py:31-35列表处理函数、review_analysis.js:21 refreshReviewAnalyses；procurement_api.py:38-47列表/详情；commerce_seller.js:281 loadProfitComparisons。
- **错误日志/测试证据/原因**：E4：固定LIMIT与前端下拉；无历史丢失证据，缺的是可达性。
- **建议修复方案**：增加稳定游标/筛选或明确按ID查看，保持租户权限和不可变快照。
- **修复验收标准**：超阈值可访问最旧记录，无遗漏重复；只读查看不触发模型或重算交易。
- **修复记录（2026-11-27）**：根因：列表固定30/20且缺替代入口。commerce_workbench.html、review_analysis.js、commerce_seller.js增加完整ID只读查看任务/比较；复用原详情接口及租户校验，不提交模型/重算。tests/test_qa_repairs_business.py隔离创建31个离线queued任务与21份比较，最旧任务及全部比较可读、跨租户404，57项针对回归通过。风险：需要完整ID，近期下拉仍限制30/20；未增加全历史分页。待独立回归。
- **独立回归（2026-11-27）**：VERIFIED｜test_old_analysis_and_comparison_remain_reachable_by_id通过：31分析/21比较及viewer可读、跨租户404；独立VM调用loadReviewById/loadComparisonById，确认完整ID转为历史选择并调用详情渲染。不要求新增分页；按ID查看是本次采用方案。


### BUG-008：切Key后残留旧一致性检查结果

- **严重程度**：P2。
- **所属模块**：设置/身份失效。
- **当前状态/证据级别**：VERIFIED。
- **详细描述/触发条件**：Key A检查后改Key B，旧integrity JSON未清除，可能误认为B结果；未证明接口越权。
- **完整复现步骤**：加载Key A；在 #settings/business-integrity 检查；输入Key B但不重新检查；观察JSON；加载B后再次核对。未实际两租户执行。
- **预期结果**：改Key立即清除或标未加载；迟到A结果不能回填。
- **实际结果**：clearSellerIdentity清空列表不含integrity，旧JSON可保留。
- **文件/类/方法/位置**：commerce_seller.js:93 clearSellerIdentity、checkIntegrity、policyVersion；commerce_workbench.html:55 integrity元素。
- **错误日志/测试证据/原因**：E4清除列表遗漏。policyVersion重置是配套建议，未单列为已发生版本错误。
- **建议修复方案**：统一失效所有私有模块DOM/状态，重置策略版本，B成功读前标未加载。
- **修复验收标准**：改Key即清空，旧响应不恢复；B仅显示B结果；既有地址/订单身份保护不退化。
- **修复记录（2026-11-27）**：根因：身份清理遗漏integrity。commerce_seller.js清除旧一致性结果及策略版本、历史ID输入；共享api维持代次校验。tests/test_qa_repairs_ui.py验证立即清空/reset，test_identity_and_busy_ui.py验证迟到响应不能回填/恢复角色；通过。遗留：等待独立回归。
- **独立回归（2026-11-27）**：VERIFIED｜test_seller_finance_metadata_and_integrity_scrub验证integrity立即清空、policyVersion归零；既有身份迟到响应测试通过。未在部署8031更换真实Key。


### BUG-009：买家会话读取故障被当作未登录

- **严重程度**：P2。
- **所属模块**：买家初始化。
- **当前状态/证据级别**：VERIFIED。
- **详细描述/触发条件**：有效Cookie下/account/me 500或断网，init捕获所有非stale错误并setBuyerSession(null)，掩盖会话读取故障。
- **完整复现步骤**：隔离账户登录；仅对/account/me注入500；重载/shop；观察身份及错误；恢复接口重试。未执行故障注入。
- **预期结果**：仅401判未登录；500/网络明确读取失败，可安全重试。
- **实际结果**：代码清空页面身份并展示登录界面；未证明服务端Cookie已失效。
- **文件/类/方法/位置**：commerce_shop_v2.html:58 api、163 init。
- **错误日志/测试证据/原因**：E4：内层catch不检查status。
- **建议修复方案**：按错误类型分流；身份未知时不展示私有信息，但区分读取失败与退出。
- **修复验收标准**：401/500/断网/stale分别正确；恢复后同账户状态可用、不串号。
- **修复记录（2026-11-27）**：根因：init所有会话异常均判未登录。commerce_shop_v2.html按401与服务故障分流；故障隐藏私有信息与登录表单，明确读取失败并提供Retry session只读恢复。tests/test_qa_repairs_ui.py注入500后恢复原账户通过；既有身份401/stale及付款忙状态测试通过（57项针对回归）。遗留：等待独立浏览器故障回归。
- **独立回归（2026-11-27）**：VERIFIED｜test_buyer_independent_reads_and_session_retry实际注入会话500后隐藏登录表单/私有信息并提示Retry session，恢复同账户通过；401/stale既有用例通过。


### BUG-010：买家订单刷新被商品或购物车故障阻断

- **严重程度**：P2。
- **所属模块**：买家订单刷新。
- **当前状态/证据级别**：VERIFIED。
- **详细描述/触发条件**：refresh-orders走refreshAll，先商品后买家；refreshBuyer又先购物车后地址/订单，无关读取失败阻断订单。
- **完整复现步骤**：已登录有订单；仅阻断GET/products而允许/my/orders；点刷新订单，查请求和陈旧状态；再仅阻断checkout-preview；恢复重试。未执行注入。
- **预期结果**：订单能独立刷新；其他模块的失败被独立标记。
- **实际结果**：loadCatalog或refreshCart抛错后不再执行后续订单读取。
- **文件/类/方法/位置**：commerce_shop_v2.html:143-149 refreshCart/refreshBuyer/refreshAll/refresh-orders.onclick。
- **错误日志/测试证据/原因**：E4顺序await调用关系。
- **建议修复方案**：独立刷新各模块并汇总结果/标记陈旧，保持身份代次及共享忙状态。
- **修复验收标准**：商品/购物车/地址单一失败不阻断其他可读模块；checkout锁不被释放；无未处理Promise。
- **修复记录（2026-11-27）**：根因：顺序await使商品/购物车失败阻断其他模块。commerce_shop_v2.html改allSettled独立读取并等待汇总结果；刷新订单只执行loadOrders，busy/身份保护保留。tests/test_qa_repairs_ui.py商品/购物车失败仍读取地址与订单，独立订单刷新通过；57项针对回归通过。遗留：等待独立回归。
- **独立回归（2026-11-27）**：VERIFIED｜test_buyer_independent_reads_and_session_retry同时注入商品/购物车失败，地址和订单仍读取；refresh-orders只调用loadOrders通过，既有买家操作锁及付款用例通过。


### BUG-011：卖家首次数据集失败后的重试不完整

- **严重程度**：P2。
- **所属模块**：工作台初始化/快速机会。
- **当前状态/证据级别**：VERIFIED。
- **详细描述/触发条件**：首次/v1/datasets失败后init停止；设置“加载工作台”仅refresh，不会补齐dataset选项。
- **完整复现步骤**：首次打开仅阻断datasets一次；恢复网络；设置点加载工作台；进快速离线机会检查dataset及品类快捷选择；尝试恢复。未执行注入。
- **预期结果**：无需整页重载即可补齐初始化依赖。
- **实际结果**：重试路径无datasets加载，选项可能持续空；整页重载可绕过。
- **文件/类/方法/位置**：commerce_workbench.html:55加载按钮、66 loadEvidence、78 init；commerce_seller.js:selectCatalogCategory（要求已有dataset option）。
- **错误日志/测试证据/原因**：E4：init与refresh职责不同、选项只在init填充。
- **建议修复方案**：提取可重试依赖加载；保留category参数和hash，不以新分析任务替代恢复。
- **修复验收标准**：首次失败后页面重试恢复；深链接不丢，重试无业务写/模型调用。
- **修复记录（2026-11-27）**：根因：datasets仅init首次加载，refresh不能补齐。commerce_workbench.html将loadSellerDatasets作为insights可重试模块依赖，保留category/hash，不提交分析。tests/test_qa_repairs_ui.py首次datasets失败不阻断分析历史、恢复后重试成功且缓存不重读；真实Chrome insights模块读取通过。遗留：等待独立深链接故障回归。
- **独立回归（2026-11-27）**：VERIFIED｜test_seller_modules_isolate_errors_retry_and_dataset_recovery注入首次datasets失败、分析历史独立读取、恢复重试/缓存通过；Chrome insights模块实际读取通过。完整原生选择控件故障点击组合未新增实点。


### BUG-012：评论进度轮询遇单次错误即停止

- **严重程度**：P2。
- **所属模块**：保存分析任务进度。
- **当前状态/证据级别**：VERIFIED。
- **详细描述/触发条件**：queued/running的/progress一次网络/500错误，catch仅notify、不再调度；后台可能继续，页面停滞。可手动查看详情恢复。
- **完整复现步骤**：隔离mock离线任务处于running；让一次progress返回500；恢复读取；观察自动刷新；点击查看详情。未执行此注入。
- **预期结果**：有限退避后恢复，或明确已暂停且提供重试入口。
- **实际结果**：pollReviewProgress错误分支没有下一次setTimeout。
- **文件/类/方法/位置**：review_analysis.js:64 loadReviewAnalysis、86-93 pollReviewProgress。
- **错误日志/测试证据/原因**：E4错误路径；未证明后台任务失败，不能以重交任务作恢复。
- **建议修复方案**：有限退避/上限/手动恢复，维持generation/id检查，切Key或任务时清理定时器。
- **修复验收标准**：瞬断恢复、持续失败不无限轮询；旧任务不渲染；恢复不新增模型调用。
- **修复记录（2026-11-27）**：根因：进度轮询catch未调度恢复。review_analysis.js最多3次1/2/4秒退避，成功重置，持续失败明确暂停并提示详情恢复；任务/身份切换不再调度旧请求。tests/test_qa_repairs_ui.py假时钟断网/上限/任务切换通过，恢复只GET不提交模型。遗留：等待独立回归。
- **独立回归（2026-11-27）**：VERIFIED｜test_progress_retry_is_bounded_and_old_task_never_reschedules通过：1/2/4秒、上限暂停、旧任务不重调度；源码复核成功重置与手动详情恢复，不重交分析任务。


### BUG-013：V1将高星隐性故障识别为正面

- **严重程度**：P2。
- **所属模块**：V1评论极性。
- **当前状态/证据级别**：BLOCKED。
- **详细描述/触发条件**：含died故障但无负向cue、五星时按positive兜底；不能推断pet_fountain V2同样失败。
- **完整复现步骤**：查看或定向运行 tests/test_polarity.py::test_known_gap_died_is_not_a_negative_cue；调用 _polarity('The pump died after three weeks',5)；对比negative断言。E1已实际xfail，本次整理不重跑。
- **预期结果**：negative。
- **实际结果**：V1高星兜底偏positive，strict xfail保留该已知失败。
- **文件/类/方法/位置**：tests/test_polarity.py:36-40；llm.py:182 _polarity；taxonomy.py:LABEL_HINTS/NEGATIVE_CUES。
- **错误日志/测试证据/原因**：E1 xfail reason：died在LABEL_HINTS却不在NEGATIVE_CUES；不是接口闭环测试能消除的语义缺口。
- **建议修复方案**：先确认规则版本/基线授权，优先隔离到新版本；不得擅改冻结V1、历史缓存或固定反例再宣称盲测提升。
- **修复验收标准**：目标版本识别故障且有反向用例；版本/缓存键和回归基线明确，历史不变；不能仅删xfail。
- **修复记录（2026-11-27）**：AGENTS.md明确冻结V1规则及历史缓存；未解除冻结授权，保留原xfail及llm.py、taxonomy和固定评估基线。


### BUG-014：请求无超时，悬挂时可能长期锁按钮

- **严重程度**：P3。
- **所属模块**：共享网络层。
- **当前状态/证据级别**：VERIFIED。
- **详细描述/触发条件**：连接一直不返回，fetch无业务超时，busy/reviewSubmitting可能一直保持；未测量浏览器/网络栈的实际超时。
- **完整复现步骤**：保持一个安全mock请求不返回；触发busy或分析提交；观察约定时限后按钮/提示；恢复连接。未执行挂起实验，当前也未定义产品超时SLO。
- **预期结果**：合理时限后有明确提示与安全恢复。
- **实际结果**：源码无AbortController/业务超时；持续时间及具体影响未测量。
- **文件/类/方法/位置**：commerce_workbench.html:64 api；commerce_shop_v2.html:58 api、63 busy；review_analysis.js:46 submitReviewAnalysis。
- **错误日志/测试证据/原因**：E4静态防护缺口，非已实测永久卡死。
- **建议修复方案**：配置合理读取超时；写超时视为结果未知，查证后重试，不能假定回滚或自动重放无幂等写。
- **修复验收标准**：挂起读取可恢复，写结果未知可查证且不重复生效；身份保护有效；正常慢请求不误杀。
- **修复记录（2026-11-27）**：采用本地演示读取30秒、写入120秒等待上限。commerce_workbench.html/commerce_shop_v2.html的requestJson覆盖fetch及响应体，超时AbortController取消并抛出可读错误；写超时明确结果未知且不自动重放，卖家同内容重试保留key。tests/test_qa_repairs_ui.py假时钟悬挂读/写验证超时、无自动重放及key复用通过；既有付款未知结果对账测试通过。风险：极慢操作也可能超时，应先查结果；待独立回归。
- **独立回归（2026-11-27）**：VERIFIED｜test_hanging_reads_and_writes_timeout_without_replay_and_keep_retry_key通过：假时钟30秒读/120秒写、无自动重发、同内容保留key；复核买卖双方requestJson均覆盖fetch与json体读取。未实际等待120秒，不把假时钟说成实测延迟。


### BUG-015：已登记退款成本缺明细核对界面

- **严重程度**：P3。
- **所属模块**：订单财务展示。
- **当前状态/证据级别**：VERIFIED。
- **详细描述/触发条件**：登记首版后仍显示空表单，没有四项净损失及依据的专门只读展示；复盘总额不足以核对。
- **完整复现步骤**：隔离库owner给已退款订单登记四项+note；刷新展开；查已有明细；用不同值再提交。未实际浏览器执行。
- **预期结果**：已有首版可核对，并说明不可覆盖。
- **实际结果**：空表单再次展示；后端相同payload重放返回成功，不同payload冲突。修正原核查报告“再次提交会冲突”的过宽表述。
- **文件/类/方法/位置**：commerce_seller.js:25 renderOrderActions、63-71 refundCostForm/saveRefundCosts、renderOrderDetail；buyers.py:300-316 settle_refund；buyers_api.py:167路由。
- **错误日志/测试证据/原因**：表单仅传id、未展示既有首版；后端错误：损失已登记，首版不支持覆盖历史记录。
- **建议修复方案**：增加授权只读记录投影/展示，保留历史，不默认缺失成本为0。
- **修复验收标准**：四项/合计/依据/已有时间可核对（未保存的时间不编造）；同payload幂等、异payload拒绝；角色写权限不变。
- **独立回归（2026-11-27）**：VERIFIED｜test_saved_refund_losses_are_recorded_only_and_immutable通过：合计60、记录时间、同payload幂等/不同payload拒绝/跨租户拒绝；独立VM renderRefundCostRecord显示依据、$0.60且无form，源码详情对已有记录不再提供空表单。


## 5. 环境问题、优化建议与规则待定项

以下保留本会话发现，不混作产品已确认故障；均P3。
- **修复记录（2026-11-27）**：根因：卖家详情未查询已登记净损失。commerce_order_views.py在租户订单校验后投影首版，commerce_seller.js展示四项/合计/依据/真实登记时间，已有首版不再展示空表单；未登记保持未知。tests/test_qa_repairs_business.py验证四项合计60、时间已记录、相同payload幂等/不同payload拒绝/跨租户拒绝；57项针对回归通过。角色校验未改；等待独立回归。


### ENV-001：测试证据目录写权限失败

- **模块/状态**：测试环境；已恢复，无业务修复待办。
- **描述/触发条件**：受限执行上下文写reports目录失败；具体ACL/策略归因未调查，不能推断应用业务写库失败。
- **复现步骤**：首轮pytest指定--junitxml reports/frontend-audit-20261126-tests.xml；执行到100%后尝试写XML；另首次node脚本mkdir reports/frontend-audit-20261126-browser。两者均实际发生。
- **预期/实际**：证据可写且完整退出；实际Python报 `PermissionError: [Errno 13] Permission denied`，Node报 `EPERM: operation not permitted, mkdir`。
- **位置/类/方法**：CLI输出路径；scripts/seller_workspace_browser_check.mjs:10 mkdir；无业务类。
- **证据/根因**：E5执行日志；环境权限，非测试断言失败。
- **建议/验收**：输出到可写目录，必要时按审批提升；pytest改临时目录取得E1，Chrome提升后取得E2，均已恢复。后续先验证输出目录，避免仅为证据路径反复重跑全套。

### OPT-001：TestClient/httpx弃用警告

- **模块/状态**：测试依赖；优化建议，待评估，非阻塞。
- **描述/条件**：全量pytest导入TestClient时出现1条弃用提示，未导致测试失败。
- **复现步骤/实际**：E1导入.venv/Lib/site-packages/fastapi/testclient.py:1；提示 `Using httpx with starlette.testclient is deprecated; install httpx2 instead.`。
- **预期**：受支持依赖组合无迁移警告。
- **位置/原因**：requirements-dev.txt、requirements.txt、requirements.lock及TestClient使用；无业务类；Starlette现版兼容迁移提示，未研究httpx2兼容性。
- **建议/验收**：评估官方兼容方案后锁定依赖，不能据警告盲换；完整接口/生命周期测试通过且警告消除，不改变真实模型禁用策略。

### OPT-002：整页重载不保留草稿

- **模块/状态**：卖家草稿；规则待定，当前明确行为，非确认bug。
- **描述/条件**：hash切换保留输入已由E2验证；整页重载不持久化，是否应保存待产品确认。
- **复现步骤/预期/实际**：填未提交成本→切hash保留→重载后默认值；此草稿重载实验本轮未另做；持久化预期未确定。
- **位置/原因**：commerce_workbench.html:59-61默认字段初始化；commerce_seller.js:renderSellerWorkspace只改hidden，无草稿存储。
- **证据/建议/验收**：E2及源码；仅新增授权后做按店铺/身份隔离草稿或离页提示，不不当保存Key/地址；按确定规则验收，不自动扩大修复范围。

### OPT-003：退款被拒后能否重新申请

- **模块/状态**：买家售后；规则待定。
- **描述/条件**：loadOrders只要已有refund记录就展示状态，无再次申请按钮；这可能是既定业务规则。
- **复现步骤/实际**：隔离库买家申请→owner拒绝→买家刷新；源码会隐藏再申请按钮；本轮未实点完整链。
- **预期**：需确认是否允许重申请，不能直接定为缺陷。
- **位置/原因**：commerce_shop_v2.html:119 loadOrders；buyers.py:request_refund后端状态约束需同步核查。
- **证据/建议/验收**：代码审查；确认规则后前后端统一，若允许须保留每次申请/审核历史和防重；若禁止则说明原因。

## 6. 修复交接与范围保护

- 原核查映射：D1→BUG-001；D2→003；D3→002/004；D4→005；D5a→006；D5→007；D6→008；D7→009/010/011/012/014；D8→015；已知xfail→013。重复项已合并，D7按可独立复现根因拆开。
- 建议顺序：001→002/003→004/005/008→009至012→006/007/015；013需单独遵守冻结版本授权；014先确认超时策略。疑似项先建立确定性失败用例。
- 待补验收：隔离mock双会话注册/地址/加购/改量/移除/下单/付款→卖家发货完成→申请退款/审核/净损失→库存与复盘；六品类机会/保存任务→候选→报价/成本GO→草稿入库上架→买家目录。
- 待补异常验证：供应商两场景及样品/接受拒绝；双报价压力比较与场景引用版本；原生CSV/JSONL合法/空/编码/格式/超量；三角色/跨店铺；断网/500/乱序/双击；到期订单及超阈值历史。只用隔离mock、保存结果，不调用live。
- 不误列缺陷：旧游客接口默认停用有账户购物车替代；卖家不代付款；GET购物车由checkout-preview覆盖。资料修改/重置密码/地址编辑删除/部分退款/签收无对应既有实现，属于新需求。
- /v1/jobs管理与/health /ready /metrics无全部商务控件，若要求每个API都有页面须另行确认范围；侧栏/看板和/console已有入口/自动测试，本轮未真实浏览器重新执行分析。
- 每修复项更新状态、版本基线、针对性验证及限制；保留编号/原证据。（原始交接时结论，现已由独立回归状态取代）当时全部业务缺陷均未修复，套件通过不等于清单已消失。


## BUG-005 重开补充：同模块强制读取乱序仍覆盖新结果

- 严重程度/模块：P2，经营复盘及模块调度（原编号延续，无重复新编号）。
- 当前状态：REOPENED。场景/比较/审计的部分修复保留，不回退原有已通过用例。
- 完整复现：加载现有卖家VM；设置sellerInitialized=true，loadSellerShared为已完成桩、moduleStatus为DOM桩，保留真实loadSellerModule/loadSellerReview；api分别保持两请求；两次调用loadSellerModule('analytics',true)；第二请求先返回[]并确认“完成第一笔”；第一请求后返回包含old-order的旧记录；最终review HTML含old-orde。详见reports/independent-regression-20261127/reproduce_bug005.py，可在项目根用.venv/Scripts/python.exe执行。
- 预期/实际：最新请求决定DOM；实际旧响应覆盖最新结果。诊断退出0及输出“BUG-005 REOPENED: stale force refresh reproduced”表示复现成功，不表示修复成功。
- 根因：commerce_workbench.html loadSellerModule(force=true)不递增每模块请求代次，sellerLoadEpoch只在reset时变化；loadSellerReview在await后直接写DOM，无模块请求序号核验。不能仅在最终moduleStatus前检查，旧数据此前已渲染。
- 建议：每模块读有独立序号/取消令牌，数据提交DOM前校验；或合并/串行force读但明确新鲜度策略；避免旧错误覆盖新成功。需验证同身份同模块、强制重试、reset、Key切换及缓存导航。
- 验收：将旧响应延迟至新响应之后仍保持新结果；反向返回顺序亦正确；旧请求不能回退状态提示；既有场景A→B→A和审计append用例继续通过。补丁会话须补回归断言“最终DOM不得含old-orde”，本诊断为问题存在性检查。
- 本轮未修业务代码；原BUG-005所有历史与修复证据保留。
