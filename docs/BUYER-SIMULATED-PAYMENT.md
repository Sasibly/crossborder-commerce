# 买家模拟支付修复（2026-11-26）

## 问题与修复

旧商城缺少买家付款接口及按钮，并提示下单后回卖家工作台付款；卖家“模拟支付成功”又受owner权限控制，operator/viewer或修改Key后临时只读的界面会禁用按钮。

现在买家在商城 `Your orders & returns` 的待支付订单下点击 `Pay $… (simulated)`，下单后自动滚动到订单区。卖家端移除代付款按钮，显示等待买家付款；付款后卖家刷新即可发货。按钮只在请求期间禁用，失败恢复以便重试。全流程不收取真实资金。

## 服务端边界

新增 `POST /shop/api/my/orders/{order_id}/pay`，正文 `{}`，需要买家会话、同源和CSRF。事务内先核对买家及店铺归属，再从已保存订单总额构造模拟事件。客户端不能指定金额、币种、结果或事件ID。其他买家/店铺404，无会话或CSRF失败401，额外字段422，取消/过期或非mock模式409。

稳定事件ID保证重复支付不重复扣库存、写事件或审计。审计身份为买家，库存/支付/审计同事务，失败全部回滚。原owner支付接口保留给兼容管理脚本与旧验收，卖家界面不再提供入口，没有放宽旧接口权限。历史游客订单不按猜测绑定买家。

## 实际验证

- 全量 **1068 passed、1 known xfailed、1 warning**，项目venv、独立临时数据库；保留V1 `died` 已知缺口和Starlette/httpx弃用提示。新增7项（含参数化）覆盖所有权/店铺/CSRF/金额防篡改、快照、幂等、买家审计、过期/取消、回滚重试、非mock拒绝及按钮状态恢复。
- 已更新8031，healthy，schema26。部署前后全表内容SHA256一致：`401b47b2495eadc6a76a52f930fbecdd2bde1a2f20f0287c9fcdff60e5bee62d`。未运行种子或完整accept/deploy验收。
- 真实隔离Chrome在1440×1000及390×844下13项检查通过，无意外控制台错误。实际通过买家页面注册虚构账户、加购、保存地址、下单、点击付款；买家和卖家均显示paid，重试仅1个支付事件，刷新后状态保留，手机无横向溢出。
- 浏览器验证8次模拟业务POST，新增虚构订单 `b4cee90bcd80462d8447966c4ee28a6c` 最后模拟退款恢复库存；原有32笔订单及所有商品内容逐项保留。测试新单及审计保留，没有删除记录或宣称测试后全库未变。
- 真实模型新增请求0，两份既有授权不得扩展。

证据：`reports/buyer-payment-20261126/` 下的tests.log、tests.xml、before.json、after-deploy.json、after-browser.json、deployment.json及browser/browser-check.json；付款前后、手机截图在browser目录。统一摘要：`docs/evidence/buyer-payment-20261126.json`。

## 使用

打开 `http://127.0.0.1:8031/shop`，必要时Ctrl+F5；登录下单的同一买家账户，在 `Your orders & returns` 点击 `Pay … (simulated)`。已支付订单不再显示付款按钮。超过15分钟应取消并重新下单，不能强行支付；卖家Key不能代替买家登录。
