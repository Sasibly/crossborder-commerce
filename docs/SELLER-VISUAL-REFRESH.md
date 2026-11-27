# 卖家端视觉与交互改造（2026-11-26）

用户确认方案后实施，仅修改卖家前端及浏览器验收脚本。买家页面、后端、数据库结构与接口均未修改。

## 交付

- `src/xborder_insight/commerce_workbench.html`：统一浅灰画布、白色细边框卡片、深蓝/蓝色品牌；调整八个视图、表格吸顶、行悬浮、字段间距与响应式布局；增加顶栏本地商品搜索、店铺及角色入口、桌面导航折叠。
- `src/xborder_insight/commerce_seller.js`：四张经营 KPI 卡片、等宽数字、订单及履约语义徽章、商品缩略图占位、原库存及上下架操作移入原生 dialog 抽屉。支持 Escape、焦点返回、关闭重开保留未提交库存数量。Key 变更关闭抽屉并清理身份展示，保留原访问代次保护。
- `scripts/seller_workspace_browser_check.mjs`：补充品牌色、KPI、折叠导航、快捷搜索、抽屉焦点及移动端输入保留验收。

保留累计模拟收款口径，不改称 GMV。无历史数据不生成涨跌趋势；成本不完整不展示利润率。店铺与角色入口展示服务端实际身份，角色切换进入现有 Key 设置。无图片使用明确的无图占位。未提供清关/承运商事件时不推断物流状态。供应商、支付及履约继续为本地模拟。

## 验证

- 19 项针对性回归全部通过：工作区导航、表单保留、订单详情、收货权限、身份失效与忙碌状态。
- 全量隔离 pytest：1080 项，1079 通过、1 项既有 V1 预期失败、1 项既有 Starlette 弃用警告；退出码 0。
- 实际隔离 Chrome：1440×1000 与 390×844，17 组验收通过。八视图无页面横向溢出；订单详情、前后导航、筛选、权限、买家界面兼容、抽屉焦点与移动端输入保留通过。无未预期控制台错误，0 业务写请求、0 新增真实模型请求。
- 对照保留的原始源码，原静态输入字段及校验属性一致，原 API/mutate 调用表达式一致。记录：`reports/seller-visual-refresh/invariants.json`。
- 部署前后数据库逻辑 dump SHA-256 相同：`ceff3a36aae2be47c79c1d84e0a5534f8f77e69ce86047dbf81e5374bab68c6f`。
- 浏览器记录及桌面/移动端截图：`reports/seller-visual-refresh/browser-check.json` 及同目录 PNG。已人工查看概览及桌面/移动端抽屉截图。

## 本机部署

已更新既有 `http://127.0.0.1:8031/workbench`，数据库卷保持不变。Docker Hub 基础镜像元数据请求连接中断，改用项目 Dockerfile 支持的已缓存 `mcr.microsoft.com/devcontainers/python:3.13` 构建并启动，未修改 Dockerfile 或 compose 配置。

源码回退快照位于 `reports/seller-visual-refresh/commerce_workbench.before.html`、`commerce_seller.before.js`。回退时恢复文件后重新构建镜像即可，无需回退数据库。
