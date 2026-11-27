# 供应商模拟与业务指标来源规范

生效日期：2026-11-25。适用于本项目后续实现。供应商模拟不是等待真实账号的临时阻塞；默认持续采用本地模拟，除非用户以后明确改变要求。

## 数据分类

| 分类 | 当前示例 | 允许的表述 | 不允许的用法 |
|---|---|---|---|
| public_survey_estimate | NRF/Happy Returns 行业退货统计 | 已核查原发布方的公开调查估计 | 写成项目 SKU 实测，或改称 2026 年数据 |
| simulation | 虚构供应商、报价、MOQ、交期、样品、状态 | 本地场景模拟，来源 local_fixture_v1 | 写成真实企业报价、实际发消息或真实供货承诺 |
| simulation | 虚构 SKU 10% 退货概率 | 没有适用实测值时的显式演示假设 | 写成由公开行业比例推导的单品概率 |
| simulation_assumptions | 采购、获客、售后费用输入 | 场景假设及对应说明 | 因旁边存在公开统计就把整份报告包装为真实经营 |

来源分类与执行环境分别记录。一份使用公开指标的决策仍可以是模拟经营；一个虚构供应商也不能降低或提升独立业务指标的来源等级。

## 已核查来源及使用范围

来源一：[NRF 2025 Retail Returns Landscape](https://nrf.com/research/2025-retail-returns-landscape)，2025-10-15 发布；线上销售预计退货占比 19.3%。

来源二：[NRF 原始发布与调查方法](https://nrf.com/media-center/press-releases/consumers-expected-to-return-nearly-850-billion-in-merchandise-in-2025)，同日发布；整体零售销售预计退货占比 15.8%，并说明商家/消费者调查范围。

核查日期为 2026-11-25，不代表数据期为 2026 年。商家来自美国大型零售商、多品类汇总，与本项目个人独立站不同；具体范围和调查方法保存在每条来源记录中。公开来源是估计而非本项目交易观测，不建立未提供的品类分布、置信区间或逐 SKU 数值。

销售退货占比不能直接当作“每件商品退货概率”。因此公开指标用于销售口径行业参照/场景曝光计算，不能直接输入单件退货损失公式；接口对错误用途返回 422。

未取得适用单品数据时，保留可选的 10% 虚构 SKU 演示概率，不暗示其适用于所有类目。未填写售后金额仍是未知成本，不因为存在行业数据就自动变成零或某个推算金额。旧咖啡机等 SKU 的 draft 假设不被覆盖或升级 verified。

## 模拟供应商流程

仅使用固定虚构身份 SIM-SUP-001，场景 standard / delayed。报价分别为 ¥70 / ¥90、MOQ 100 / 200、交期 14 / 30 天，全部是演示设定；没有真实名称、联系人、邮箱、外部 URL 或凭证。

流程：draft → rfq_sent → quoted → sample_requested → sample_received → accepted，支持中途 rejected；所有按钮和记录明确标记模拟。状态采用版本校验，过期请求返回 409，不重复推进；事件写入与状态变化、审计在同一事务。

不调用供应商网络、不发邮件或消息、不触发采购付款。真实支付及物流也继续沿用已有模拟，不再将获取供应商系统凭证作为项目完成前提。

选品引用报价时校验租户、候选商品、可用状态和采购金额。保存报价版本快照后，后续模拟接受、拒绝或样品流程不会修改既有决策。

## 替换和扩展

- 指标目录位于 src/xborder_insight/business_metrics.json，随代码版本发布、离线可读；不会被 Docker 数据卷遮蔽，也不要求运行时抓取外网。
- 每条记录包含版本 ID、值、单位、统计口径、来源类型、发布方、URL、发布日期、核查日、期间、市场、渠道、品类、方法和假设。
- 新年份、新品类或新的真实观测应添加新 ID，不就地改旧版本。决策保存来源全文快照，旧决策可复算。
- 未来若增加真实指标数据集，仍单独验证分母、窗口、样本和适用范围；供应商继续模拟，不需要同时替换。
- 全部模拟订单导出的汇总仍标 simulation，不能登记为真实卖家历史读数。

## 实现与验收

新增 0023 迁移保存模拟供应商状态和事件，data_kind 用数据库约束固定为 simulation。API 不接受 supplier_url 等额外真实接入参数。

`/v1/commerce/business-metrics` 展示来源目录；`/metric-scenario` 按来源用途约束计算；`/supplier-cases` 创建/读取模拟流程。决策可携带 returns_metric_id 和 supplier_quote_id，分别存入 returns_metric_reference 与 supplier_quote；data_provenance 区分模拟采购和公开指标。

本轮全量：862 passed、1 xfailed、1 warning（863 项，47.13 秒）。新增测试覆盖状态机、版本冲突、租户隔离、报价绑定、历史快照、公开口径误用及模拟回退。原有已知规则 xfail 和 TestClient 弃用警告未变。

Docker 重建并迁移到 23，原交易烟测通过。浏览器实际创建模拟询价、模拟返回报价、保存新决策，确认 supplier_quote.data_kind=simulation 与 returns_metric_reference.source_kind=public_survey_estimate 同时存在；期间为 2025，引用用途 reference_only，售后成本不被覆盖。前端 error 日志为空。
