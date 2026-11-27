# 商品品类空白修复（2026-11-26）

## 原因

排查时本机8031的catalog-stages接口返回6个品类、state返回24件商品，数据没有缺失。旧clearSellerIdentity会在每次Key input事件中清空商品与品类选项，包括Key值未变化的事件。被清空的select仍可点击，且之后调用本地筛选会显示0/0，没有说明尚未重新加载；可复现与用户截图一致的空白状态。静态截图不能证明该事件由用户输入、浏览器填充还是其他具体操作触发。

## 修复

- Key输入先比较值；未变化不清空已加载数据。实际Key变化仍清除私有状态，A→B→A仍使旧请求失效。
- 为品类控件增加loading、identity_changed、error、ready状态。前三种状态显示明确占位与原因、暂时禁用品类选择，不把未加载或失败显示成没有商品。
- 商品区新增只读“刷新商品与品类”按钮，成功后恢复完整选项及商品列表，并显示成功提示。真正成功加载的空商品集合仍显示0/0，区别于加载失败。
- 保留原刷新调度、模块路由、商品抽屉及界面样式。本轮未继续待批准的按分区加载重构，没有业务API、schema、成交快照或权限放宽。

## 实际验证

- 全量1081 passed、1 known xfailed、1 warning；新增2项恢复回归，原商品筛选夹具显式标记为已加载。保留既有V1缺口和Starlette/httpx弃用提示。
- 真实隔离Chrome在1440×1000及390×844下18项检查通过，无意外控制台错误。确认未变化Key事件保留选项，真实变更清空地址并显示待加载；注入品类GET失败后显示错误，经页面按钮恢复；使用原生select的End键选中无线充电器并实际过滤到3件商品。其他筛选、导航、桌面手机商品抽屉均通过。
- 本机8031已更新，healthy、schema26。部署前后及只读浏览器检查后全表内容SHA256一致：54cb3db2c2c85baeb596334a916193936ac767a6f723fe581a60adb9361b4ecf。
- 浏览器仅发起122次GET，业务写入0，真实模型请求0。未调用种子或完整accept/deploy验收。

证据目录：reports/seller-category-recovery-20261126；测试日志tests.log/xml，浏览器报告browser/browser-check.json，恢复后的筛选截图browser/desktop-category-recovered.png，数据库备份摘要before/after-deploy/after-browser.json，最终状态deployment.json。统一摘要：docs/evidence/seller-category-recovery-20261126.json。

用户操作：打开商品与库存，必要时Ctrl+F5。如果出现待重新加载或加载失败提示，点击“刷新商品与品类”。正常加载后为“全部品类”加6个实际品类，并显示每类商品数量。
