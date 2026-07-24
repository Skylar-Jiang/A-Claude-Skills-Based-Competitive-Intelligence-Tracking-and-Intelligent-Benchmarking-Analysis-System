# 组员一（杨滢）阶段汇报：系统数据收集处理与客服 Agent 落地

## 1. 汇报范围

本汇报结合以下材料整理：

- `docs/plans/2026-07-14-pet-supplies-data-pipeline.md`
- `docs/plans/2026-07-19-customer-service-agent-api.md`
- 当前仓库截至 2026-07-19 的代码与测试状态

本部分对应组员一职责：商品数据收集与清洗、商品标准化、离线数据准备、同类商品匹配、SQL 市场统计分析，以及报告生成后的 `CustomerServiceAgent` 设计与落地。

## 2. 负责模块总览

组员一主要负责两条主线：

1. 数据侧主线：围绕 `pet_supplies` 真实商品与评论数据，完成预处理、导入、清洗、标准化、索引/缓存准备、同类商品候选准备与统计分析支撑。
2. 交互侧主线：围绕报告生成后的用户反馈闭环，完成 `CustomerServiceAgent` 后端接口、会话状态维护、多轮修改与增量更新能力。

## 3. 当前完成情况概览

### 3.1 已完成部分

- `pet_supplies` 真实数据预筛选、导入、清洗、评论裁剪与基础统计链路已落地。
- 商品领域配置、领域适配器、SQL 统计 Provider 已接入现有系统。
- 客服 Agent 后端接口、会话状态、意图识别、回复风格切换、多轮对话与增量改写链路已落地。
- 相关单元测试与集成测试已补齐，已有阶段性验证结果。

### 3.2 部分完成/需继续补齐部分

- 同类商品匹配能力已经有基础代码与配置，但目录结构与原始分工文档不完全一致，当前主要落在 `app/domain/` 与 `app/services/`，不是 `app/peer_matching/`。
- SQL 市场统计当前已完成基础指标计算，但距离职责说明中的“中位数、区间分布、品牌分布、功能分布、热度、缺失情况”等全量指标，还有继续扩展空间。
- 轻量商品目录、全文检索索引、评论位置索引、缓存签名/过期检查相关能力已有边界测试与准备脚本支撑，但还可以继续向更完整的线上可复用缓存体系收敛。

### 3.3 当前未按原文目录落地的点

- 原分工中写到的 `app/peer_matching/` 目录当前仓库中不存在。
- 当前实际相关实现主要位于：
  - `app/domain/peer_matching.py`
  - `app/domain/peer_data.py`
  - `app/services/peer_group_service.py`
  - `scripts/prepare_peer_data.py`
  - `config/peer_matching.yaml`

## 4. 具体工作对照说明

### 4.1 数据整理与清洗

已完成面向 `pet_supplies` 真实数据的离线处理链路，覆盖商品元数据、评论数据、重复/异常处理和标准化导入流程。

已落地文件包括：

- `scripts/domain_imports/prefilter_pet_supplies.py`
- `scripts/domain_imports/prefilter_pet_supplies_reviews.py`
- `scripts/domain_imports/import_pet_supplies.py`
- `scripts/domain_imports/prune_pet_supplies_reviews.py`
- `scripts/domain_imports/clean_pet_supplies.py`

当前能力包括：

- 按领域条件筛选原始商品数据与评论数据。
- 过滤缺失价格、缺失标题、缺失 `parent_asin` 等无效记录。
- 导入 `products`、`competitor_offers`、`reviews`、`knowledge_sources`。
- 处理重复评论 ID，避免重复导入。
- 保留 `source_file`、`source_line`、`parent_asin` 等追溯信息。
- 通过可重复执行的脚本完成离线准备，避免手工清洗。

### 4.2 商品信息标准化

已完成基础标准化能力，重点围绕商品标题、价格、评分、品牌、类目路径、图片/视频数量、部分属性字段清洗。

当前已覆盖的标准化方向：

- 商品名称：`title` 清洗与归一化。
- 商品价格：价格字段标准化。
- 商品品牌：优先从 `details.Brand` 提取，必要时回退到 `store`。
- 商品类别：稳定化类目路径与子类目路径。
- 商品参数/特点：保存在 `attributes_json`、`metadata_json` 中。
- 目标宠物/适用对象：支持从类目和细节中提取 `species`。

说明：

- 责任书中要求的“商品描述、功能、参数、特点、使用场景、目标用户/目标宠物、品牌、价格、类别”等字段，当前已实现大部分基础抽取与结构化存储。
- 若后续答辩或验收要求展示更细粒度字段映射，可继续基于 `clean_pet_supplies.py` 扩展更明确的标准字段输出。

### 4.3 离线数据准备

该部分已有明确实现基础，核心目标是让在线分析不再重复扫描完整原始数据。

当前支撑点包括：

- 预筛选后的商品与评论 JSONL 文件。
- 导入后的本地 SQLite 数据库。
- `knowledge_sources` 文本证据入库。
- `scripts/prepare_peer_data.py` 提供同类商品准备脚本。
- `tests/integration/test_peer_data_preparation_boundary.py`
- `tests/integration/test_product_catalog_cache.py`
- `tests/integration/test_review_lookup_cache.py`

阶段判断：

- “避免在线阶段重新扫描完整原始数据”这一目标已基本达成。
- “缓存签名、生成时间、缺失与过期检查”已有基础设计方向，但若要完全对应职责说明，建议后续在缓存元数据层再做一轮显式强化。

### 4.4 同类商品候选召回

当前仓库已具备同类商品准备与匹配的基础模块，但实现位置与最初目录规划不同。

相关文件包括：

- `app/domain/peer_matching.py`
- `app/domain/peer_data.py`
- `app/services/peer_group_service.py`
- `config/peer_matching.yaml`
- `tests/unit/domain/test_peer_matching.py`
- `tests/unit/domain/test_peer_matching_semantics.py`
- `tests/unit/test_peer_group_service.py`
- `tests/unit/agents/test_peer_group_agents.py`

从职责匹配角度看，当前已经覆盖：

- 同类商品召回配置化。
- 规则匹配与语义匹配测试基础。
- `peer_group` 服务层支撑。

需要说明的是：

- 当前目录不是原文中的 `app/peer_matching/`，而是整合到了 `app/domain/` 和 `app/services/`。
- 从代码组织上看，候选召回与匹配逻辑已经开始落地，但在汇报表述上更适合写成“基础能力已完成，正在向稳定化与效果优化推进”。

### 4.5 语义排序与匹配过滤

这部分当前已有配置和测试基础，说明系统已经考虑了规则匹配与语义匹配结合的方向。

已具备的落地点：

- `config/peer_matching.yaml`
- `tests/unit/domain/test_peer_matching_semantics.py`

可汇报为：

- 系统已经预留并实现了“规则 + 语义”的同类商品匹配框架。
- 已支持通过配置管理匹配策略，为后续阈值优化、版本管理和效果调参提供基础。

需要如实说明的边界：

- 从当前仓库结构看，这部分已具备实现雏形和测试，但若按职责书要求追求完整验收，还需要继续强化阈值管理、数据不足状态返回、稳定匹配版本记录等细节。

### 4.6 同类商品组标识

当前仓库已有 `peer_group` 相关服务与测试，说明稳定分组标识这部分已经开始工程化。

相关文件：

- `app/services/peer_group_service.py`
- `tests/unit/test_peer_group_service.py`

可汇报重点：

- 已建立 `peer_group` 相关服务层，支持同类商品组的组织与管理。
- 已为后续稳定 `peer_group_id`、匹配依据记录和上传数据隔离打下基础。

建议表述：

- 当前属于“核心机制已铺设，稳定性与全流程验证仍可继续增强”的状态。

### 4.7 SQL 市场统计

该部分已经实装基础版 SQL 统计 Provider，并完成系统接线。

核心文件：

- `app/statistics/providers/pet_supplies.py`
- `app/statistics/factory.py`
- `tests/unit/statistics/test_pet_supplies_provider.py`
- `tests/integration/test_statistics_injection.py`

当前已完成指标包括：

- `offer_count`
- `priced_offer_count`
- `avg_price`
- `min_price`
- `max_price`
- `avg_rating`
- `total_rating_count`

与职责书对照：

- 基础数量、价格、评分相关统计已完成。
- 中位数、价格区间、评论数量分布、品牌分布、功能特点分布、热度情况、数据缺失情况等扩展指标，后续仍可继续补齐。

### 4.8 CustomerServiceAgent

客服 Agent 后端能力当前已经不是纯方案，而是已有代码、路由、Schema 和测试的可联调状态。

核心文件包括：

- `app/services/customer_service_agent_service.py`
- `app/services/conversation_service.py`
- `app/services/report_support_service.py`
- `app/schemas/customer_service.py`
- `app/api/v1/router.py`
- `scripts/customer_service_smoke.py`
- `tests/unit/test_customer_service_schemas.py`
- `tests/unit/test_customer_service_routing.py`
- `tests/integration/test_customer_service_api.py`

当前已实现能力包括：

- 接收用户对报告的追问、修改意见和补充需求。
- 识别用户意图，如解释、局部改写、定向增量更新、澄清、拒绝超范围需求。
- 维护多轮会话上下文，包括 `conversation_id`、修改历史、已确认需求、待澄清问题、最新报告版本等。
- 支持多种人格风格：`simple`、`professional`、`companion`、`innovative`。
- 根据用户反馈对指定模块执行增量更新，而不是每次全量重跑报告。
- 打通“方案生成 -> 用户反馈 -> Agent 优化 -> 方案更新”的后端闭环。

当前开放的主要接口：

- `POST /api/v1/reports/{report_id}/customer-service/messages`
- `GET /api/v1/reports/{report_id}/customer-service/conversations/{conversation_id}`

## 5. 代码目录映射说明

结合原始分工与当前仓库，建议在汇报中这样表述“责任目录”：

### 已直接对应

- `app/adapters/`
- `app/statistics/`
- `scripts/prepare_peer_data.py`
- `scripts/domain_imports/`
- `config/peer_matching.yaml`

### 实际落地路径与原文有差异

- 原文：`app/peer_matching/`
- 实际：`app/domain/peer_matching.py`、`app/domain/peer_data.py`、`app/services/peer_group_service.py`

### 测试目录实际情况

- 原文：`tests/unit/peer_matching/`
- 实际：
  - `tests/unit/domain/test_peer_matching.py`
  - `tests/unit/domain/test_peer_matching_semantics.py`
  - `tests/unit/test_peer_group_service.py`
  - `tests/unit/agents/test_peer_group_agents.py`
- 原文：`tests/unit/statistics/`
- 实际：
  - `tests/unit/statistics/test_pet_supplies_provider.py`

## 6. 阶段性验证结果

结合计划文档和现有交接记录，当前已有以下阶段性结果：

- `pet_supplies` 数据链路相关定向验证结果：`18 passed`
- `CustomerServiceAgent` 相关测试结果：`12 passed, 1 warning`

可支撑的阶段性结论：

- 数据导入、清洗、领域适配、统计接线链路可运行。
- 客服 Agent 接口已进入可联调状态，具备多轮反馈与增量改写能力。

## 7. 当前主要交付物

### 数据链路与标准化

- `config/domain_profiles/pet_supplies.yaml`
- `scripts/domain_imports/prefilter_pet_supplies.py`
- `scripts/domain_imports/prefilter_pet_supplies_reviews.py`
- `scripts/domain_imports/import_pet_supplies.py`
- `scripts/domain_imports/prune_pet_supplies_reviews.py`
- `scripts/domain_imports/clean_pet_supplies.py`
- `app/adapters/domains/pet_supplies.py`
- `app/statistics/providers/pet_supplies.py`
- `app/statistics/factory.py`

### 同类商品匹配与离线准备

- `scripts/prepare_peer_data.py`
- `app/domain/peer_matching.py`
- `app/domain/peer_data.py`
- `app/services/peer_group_service.py`
- `config/peer_matching.yaml`

### CustomerServiceAgent

- `app/services/customer_service_agent_service.py`
- `app/services/conversation_service.py`
- `app/schemas/customer_service.py`
- `app/api/v1/router.py`
- `scripts/customer_service_smoke.py`

### 主要测试

- `tests/integration/data/test_pet_supplies_prefilter.py`
- `tests/integration/data/test_pet_supplies_reviews_prefilter.py`
- `tests/integration/data/test_pet_supplies_import.py`
- `tests/integration/data/test_pet_supplies_prune_reviews.py`
- `tests/integration/data/test_pet_supplies_clean.py`
- `tests/integration/data/test_pet_supplies_adapter.py`
- `tests/unit/statistics/test_pet_supplies_provider.py`
- `tests/integration/test_statistics_injection.py`
- `tests/integration/test_peer_data_preparation_boundary.py`
- `tests/integration/test_product_catalog_cache.py`
- `tests/integration/test_review_lookup_cache.py`
- `tests/unit/domain/test_peer_matching.py`
- `tests/unit/domain/test_peer_matching_semantics.py`
- `tests/unit/test_peer_group_service.py`
- `tests/unit/test_customer_service_schemas.py`
- `tests/unit/test_customer_service_routing.py`
- `tests/integration/test_customer_service_api.py`

## 8. 存在的问题与下一步建议

### 当前存在的问题

- 原始分工文档中的部分目录名称与实际仓库落地不完全一致，汇报时需要主动说明。
- 同类商品匹配链路已有基础，但如需严格对应职责书，还需要进一步强化稳定分组、阈值管理、数据不足提示和匹配依据输出。
- SQL 市场统计当前以基础指标为主，尚未完全覆盖中位数、分布、热度、缺失情况等扩展分析项。

### 下一步建议

1. 继续补齐同类商品匹配链路的稳定化细节，包括阈值、版本、匹配依据记录和不足样本返回。
2. 扩展 SQL 市场统计指标，重点补齐中位数、区间分布、品牌分布、评论分布与缺失情况。
3. 将离线缓存签名、更新时间、过期判断等元信息进一步显式化，便于线上复用和验收展示。
4. 在客服 Agent 侧补更多 smoke/e2e 场景，增强联调与答辩展示稳定性。

## 9. 汇报结论

截至 2026-07-19，组员一负责的“系统数据收集处理与客服 Agent 落地”已经完成了核心主链路建设：

- 数据侧已完成真实 `pet_supplies` 数据的预处理、导入、清洗、标准化、领域适配和基础统计支撑。
- 交互侧已完成报告生成后的 `CustomerServiceAgent` 后端闭环，实现了多轮反馈、风格切换、局部改写和增量优化。
- 同类商品匹配与离线准备能力已经有工程化基础，但仍有部分细节值得继续补强，以更完整对齐最初分工要求。

整体上，这一部分工作已经从“方案设计”进入“可运行、可测试、可联调”的阶段，可支撑后续组内整合、前后端联调和阶段汇报展示。
