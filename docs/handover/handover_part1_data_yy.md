# 第一部分历史交接说明：领域数据、清洗与 SQL 统计

> 历史实施记录；最终 peer-group 生产主链以 `docs/handover/handover.md` 为准。

## 一、负责范围

本次交接对应队友一在 `pet_supplies` 真实领域下的工作范围，主要包括：

- 最终真实领域配置
- 真实商品、竞品报价、评论数据导入
- 数据清洗、去重、字段标准化
- 来源记录与数据追溯
- 基于 SQL 的确定性统计
- 用真实统计 Provider 替换当前 Stub

## 二、已完成内容

### 1. 真实领域配置已完成

已新增：

- `config/domain_profiles/pet_supplies.yaml`

当前运行时已经可以加载 `pet_supplies` 领域配置，并正确解析到对应的真实领域适配器。

### 2. 真实数据导入已完成

已新增：

- `scripts/domain_imports/import_pet_supplies.py`

该导入脚本已经完成真实 `pet_supplies` 数据导入，导入目标包括：

- `products`
- `competitor_offers`
- `reviews`
- `knowledge_sources`

当前导入逻辑支持幂等重跑。此前出现过一次 `reviews.review_id` 唯一键冲突问题，现已通过改进确定性 `review_id` 生成规则和同批次重复跳过逻辑修复。

### 3. 数据清洗、去重和标准化已完成

已新增或更新：

- `scripts/domain_imports/clean_pet_supplies.py`

清洗脚本已覆盖商品、报价、评论和商品知识文本的标准化处理，主要包括：

- 价格标准化
- 平均评分标准化
- 评分人数标准化
- 品牌字段归一
- 类目路径标准化
- `species` 提取
- 图片与视频数量标准化
- 清洗阶段标记写入元数据

此外，清洗脚本已经补充运行进度输出，便于大规模真实数据执行时观察进度。

### 4. 精简评论集裁剪已完成

已新增：

- `scripts/domain_imports/prune_pet_supplies_reviews.py`

由于后续开发阶段将评论数据集从早期更大规模的全量导入切换为精简后的 filtered reviews 数据集，因此已补充数据库评论裁剪逻辑，使数据库中的真实评论与当前最新 filtered review 文件保持一致。

该裁剪脚本仅删除多余的 `pet_supplies` 历史评论，不会误删商品、报价或元数据记录。

### 5. 来源记录与数据追溯已完成

当前导入和清洗后的记录中，已经保留了来源和追溯信息，典型字段包括：

- `source_file`
- `source_line`
- `parent_asin`

领域特有字段优先存放在：

- `attributes_json`
- `metadata_json`

本次实现未改动公共数据库结构。

### 6. 真实领域适配器已完成

已新增：

- `app/adapters/domains/pet_supplies.py`

`PetSuppliesDomainAdapter` 当前会直接复用已经导入并清洗过的真实商品数据，而不是生成 demo fixture。同时会把已导入的商品知识文档注入到运行时使用的 `KnowledgeStore` 中。

### 7. SQL 统计 Provider 已完成

已新增：

- `app/statistics/providers/pet_supplies.py`

该 Provider 已经可以通过 SQL 返回确定性统计结果，并且输出符合 `StatisticsResult` 契约。当前已实现的统计指标包括：

- `offer_count`
- `priced_offer_count`
- `avg_price`
- `min_price`
- `max_price`
- `avg_rating`
- `total_rating_count`

### 8. 真实统计 Provider 接线已完成

已更新：

- `app/statistics/factory.py`

当前运行时已经能够在 `pet_supplies` 真实路径下选择 `PetSuppliesStatisticsProvider`。对于 demo 产品路径，仍然保留 scaffold provider 的回退行为。

本次没有修改 `StatisticsProvider` 和 `StatisticsResult` 契约定义。

## 三、最终导入与保留数据量

当前数据库中最终保留的真实 `pet_supplies` 数据规模如下：

- `products`：`161540`
- `competitor_offers`：`161540`
- `knowledge_sources`：`161540`
- `reviews`：`591406`

补充说明：

- 数据库中早期曾存在一次更大规模的全量评论导入
- 后续已根据新的 filtered review 文件执行裁剪
- 本次共删除历史残留评论：`4555651`
- 裁剪后最终保留评论数：`591406`

## 四、验证结果

已完成定向验证，结果全部通过。

执行命令：

```powershell
conda run -n shixun python -m pytest tests/integration/data tests/unit/statistics tests/integration/test_statistics_injection.py tests/unit/test_domain_profiles.py tests/unit/test_workflow.py -v
```

验证结果：

- `18 passed`

覆盖内容包括：

- metadata prefilter
- review prefilter
- import
- review pruning
- clean
- domain profile
- domain adapter
- SQL statistics provider
- statistics injection
- workflow integration

## 五、本次交付的主要文件

本次主要交付文件如下：

- `config/domain_profiles/pet_supplies.yaml`
- `app/adapters/domains/pet_supplies.py`
- `app/statistics/providers/pet_supplies.py`
- `app/statistics/factory.py`
- `scripts/domain_imports/import_pet_supplies.py`
- `scripts/domain_imports/clean_pet_supplies.py`
- `scripts/domain_imports/prune_pet_supplies_reviews.py`
- `tests/integration/data/test_pet_supplies_import.py`
- `tests/integration/data/test_pet_supplies_clean.py`
- `tests/integration/data/test_pet_supplies_prune_reviews.py`
- `tests/integration/data/test_pet_supplies_adapter.py`
- `tests/unit/statistics/test_pet_supplies_provider.py`
- `tests/unit/test_domain_profiles.py`
- `tests/integration/test_statistics_injection.py`

## 六、公共契约与结构安全性说明

本次实现没有直接修改以下公共契约或公共数据库结构文件：

- `app/statistics/contracts.py`
- `app/adapters/base.py`
- `app/workflows/state.py`
- `app/workflows/graph.py`
- `app/db/models/core.py`
- `app/db/repositories/protocols.py`
- `migrations/versions/20260714_0001_initial_schema.py`

## 七、可交接状态

当前 `pet_supplies` 领域已经具备以下可供后续同学直接使用的基础能力：

- 可加载的真实 `DomainProfile`
- 可运行的真实 `DomainAdapter`
- 已导入并清洗完成的真实商品与评论数据
- 可直接消费的 SQL `StatisticsResult`
- 可追溯的数据来源记录

后续队友二可以在此基础上继续推进：

- `product_knowledge` / `review_insight` 的 RAG 组织与检索
- `ProductMarketAgent`
- `UserInsightAgent`

## 八、本地数据库导入说明

如果其他同学需要在本地复现 `pet_supplies` 数据导入，可以直接基于已经预处理完成的数据文件进行导入，不需要重新跑原始大文件预处理。

当前预处理后的数据文件位置为：

- `\TradePilot\data\filtered`

主要使用的输入文件为：

- `data/filtered/meta_pet_supplies_prefiltered.jsonl`
- `data/filtered/pet_supplies_reviews_prefiltered.jsonl`

建议在 `shixun` conda 环境下执行以下步骤。

如果本地还没有历史导入数据，可以直接执行：

```powershell
conda run -n shixun python scripts/init_db.py
conda run --live-stream -n shixun python -u scripts/domain_imports/import_pet_supplies.py --metadata-input data/filtered/meta_pet_supplies_prefiltered.jsonl --reviews-input data/filtered/pet_supplies_reviews_prefiltered.jsonl
conda run --live-stream -n shixun python -u scripts/domain_imports/clean_pet_supplies.py
```

### 导入完成后的预期规模

当前这批 `pet_supplies` 真实数据完成导入、裁剪和清洗后，数据库中应保留：

- `products`：`161540`
- `competitor_offers`：`161540`
- `knowledge_sources`：`161540`
- `reviews`：`591406`

### 关于 `tradepilot.db`

`tradepilot.db` 是项目当前默认使用的本地 SQLite 数据库文件，作用是保存运行时需要的结构化数据，包括：

- 商品表 `products`
- 竞品报价表 `competitor_offers`
- 评论表 `reviews`
- 知识来源表 `knowledge_sources`
- 分析运行记录、报告记录、会话记录等其他业务表

默认情况下，导入脚本、清洗脚本和运行时读取的本地数据库就是这个文件，路径通常是：

- `data/tradepilot.db`

如果队友需要重新导入本地数据，本质上就是把预处理后的 JSONL 数据导入到这个 SQLite 文件中。
