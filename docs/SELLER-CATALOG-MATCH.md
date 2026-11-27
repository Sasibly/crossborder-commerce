# 卖家与商城商品对照（2026-11-26）

## 问题与核对

用户反馈商城出现卖家没有的机器人吸尘器、宠物喷泉。8031 实测两端店铺均为 local；卖家共24件商品，其中9件已上架。商城9件商品按完整 SKU、原名称、价格和库存逐项对应卖家的已上架集合，没有商城独有商品。截图中的六个选项是品类，并非六件商品；扫地机器人对应 Robot vacuums，宠物饮水机对应 Pet fountains。

## 修改

卖家商品品类增加中英文对照及该品类总数、已上架数量；商品卡片保留商城相同的原商品名和 SKU，品类中英文均可搜索。显示当前组合筛选，并提供“查看商城已上架商品”和“清除筛选，查看全部商品”入口，清除不相关的搜索、状态和品类条件。入口可供 viewer 使用，不执行业务写入。未知品类与服务端一样归入其他。

没有改写商品、候选、订单历史快照，没有删除或补造商城商品。

## 实际验证

- 相关14项测试通过：seller_workspace、catalog_categories、seller_orders_ui、seller_order_details；保留1项既有 Starlette/httpx 弃用提示。本轮未重跑全量测试。
- 已构建并更新本机8031容器，schema26，healthy；使用 compose build/up，不运行会创建记录的 deploy/verify/accept 或种子脚本。
- 实际隔离Chrome在1440×1000与390×844下12项检查通过，无意外控制台错误。新增核对两端已上架 SKU/原名/价格/库存集合，以及中英文品类、数量和清除筛选入口。只发送100次GET，业务写入0，真实模型请求0。
- 浏览器证据：`reports/seller-catalog-match-20261126/browser-check.json`，商品页截图：`reports/seller-catalog-match-20261126/desktop-products.png`。
- 更新前备份：`/app/data/local-verification/20261126T080909Z-34b4aac1/backup.sqlite3`；更新后备份：`/app/data/local-verification/20261126T081018Z-d0c6e722/backup.sqlite3`。均验证新文件恢复完整性。
- 更新前后全表内容SHA256均为 `12bc08a02360d4db3ac18bfeaa31e7da4ec9beb1229f8104ddc7da2b6aff7f60`，24件商品及31笔历史订单完整保留。本轮基线按更新前实际状态捕获，不与更早验收时的用户操作状态混同。
- 执行git diff仍提示目录不是Git仓库，未初始化Git。

首次测试因旧pytest临时目录拒绝访问而在初始化阶段报错，改用新的独立basetemp后14项全部通过。

打开 `http://127.0.0.1:8031/workbench#products/product-list`，必要时Ctrl+F5，点击“查看商城已上架商品”即可逐件对照买家商城。商城只显示已上架商品，草稿和已下架商品留在卖家侧；缺货的已上架商品仍在商城展示。
