# 第三部分合并说明：运营决策、证据审校与报告导出

## 一、合并状态

- 功能分支：`decision/team-three-operations`
- 功能提交：`79a5c7c feat: implement operations decision audit and reports`
- 合并提交：`1a58206 merge: teammate three operations implementation`
- 合并目标：`main`
- 当前状态：已合并并推送到远端 `main`

2026-07-14 复核时，GitHub Compare API 显示当前远端 `main` 以 `1a58206` 为合并基点，
并在其后继续增加了 5 个队友一提交。因此队友三功能提交已处于当前主分支历史中，不需要管理员再次合并。

## 二、本次负责范围

本次实现对应 `docs/team-work-split.md` 中队友三的当前阶段职责：

- `OperationsDecisionAgent`
- `EvidenceAuditAgent`
- `OperationContentSkill`
- 标题、卖点、描述、广告关键词和客服话术规则
- 结论与证据对应
- 冲突检测、数值审校和文案合规检查
- 最多一次回退所需的具体整改信息
- 最终报告内容、展示结构和版本号
- 相应单元测试与集成测试

正式前端仍按团队分工文档保留到后续阶段。本次没有绕过 OpenAPI 直接读取数据库、报告目录或
`data/` 文件，也没有修改冻结的 API、共享 Schema 或 LangGraph 拓扑。

## 三、已完成内容

### 1. 运营决策 Agent

主要修改文件：

- `app/agents/operations_decision.py`

已完成：

- 汇总 `ProductMarketAnalysis` 与 `UserInsight` 的证据编号并去重。
- 汇总商品、市场分析和用户洞察中的 `DataGap`。
- 根据目标市场、目标用户和已确认商品特征生成定位建议。
- 无证据时将结果降级为 `insufficient_evidence`，并明确记录数据缺口。
- 生成结构化 `Conclusion`，区分建议、用户输入和数据限制。
- 用户提供目标价格时，仅将该价格标记为用户输入，不把它伪装成市场统计。
- 调用 `OperationContentSkill` 生成运营文案草稿。
- 保持 `data_origin`、`implementation_status` 和现有 `OperationPlan` 合同不变。

### 2. OperationContentSkill

主要新增或修改文件：

- `app/skills/operation_content/__init__.py`
- `app/skills/operation_content/skill.py`
- `app/skills/operation_content/skill.yaml`
- `app/skills/operation_content/README.md`

已完成：

- 将 Skill 配置升级为启用状态的 `1.0.0` 版本。
- YAML 中维护标题、五点卖点、描述、关键词和客服模板规则。
- 生成商品标题、5 条卖点、商品描述、最多 10 个关键词。
- 生成兼容性、物流、问题处理和退货四类客服话术。
- 配置并检查 `#1`、`100%`、`best`、`guaranteed`、`FDA approved`、
  `lowest price`、`risk-free` 等禁止或无证据表达。
- 对标题、卖点数量、文本长度、关键词数量和客服模板完整性进行校验。
- 所有内容只使用 `ProductProfile` 中已提供的信息，避免自行生成销量、评分、价格和认证数值。

由于共享 `OperationPlan` Schema 属于冻结合同，本次没有私自新增公共字段。文案内容通过稳定前缀写入
`OperationPlan.next_steps`，报告导出时再恢复为结构化 `content_playbook`。这样既完成业务功能，
又不会破坏其他队友和前端依赖的接口。

### 3. 证据审校 Agent

主要修改文件：

- `app/agents/evidence_audit.py`

已完成：

- 检查商品和运营方案的 `data_origin` 是否一致，防止 Demo 与真实数据混用。
- 检查结论引用的证据编号是否已在方案中声明。
- 事实类结论缺少证据且未声明数据缺口时返回 `rejected`。
- 检查未经验证的百分比、数量和其他数值声明。
- 检查禁止营销表达及运营文案规则。
- 检查低价与高端、耐用与易碎、便携与笨重等相互冲突的语义定位。
- 检查方案是否否认商品中已经声明的已知风险。
- 检查目标市场是否体现在定位或后续行动中。
- 保留 `pass`、`warning`、`rejected` 三种结果。
- `rejected` 时设置 `manual_review_required=true`，并返回具体字段位置、问题原因和修改建议。
- 将冲突证据编号、未解决问题和缺失数据写入 `AuditResult`，供现有 LangGraph 最多一次回退使用。

本次没有在 Agent 内部创建循环，仍由既有 `app/workflows/graph.py` 控制最多一次回退。

### 4. 报告导出

主要修改文件：

- `app/services/report_exporter.py`

已完成：

- 报告版本按 `state.report_version + 1` 递增，最低为版本 1。
- JSON 报告新增 `executive_summary`、`content_playbook`、`data_limitations`、
  `evidence_index` 和 `next_actions` 等结构化模块。
- Markdown 报告新增执行摘要、关键结论、运营文案、证据审校、数据限制、证据索引和后续行动章节。
- 证据审校失败时在报告顶部显示“需要人工审核”提示。
- 继续保留 Demo 免责声明和 `implementation_status=scaffold` 标识。
- 继续输出现有合同支持的 JSON 与 Markdown 路径，没有私自扩展共享报告 Schema。

### 5. 测试覆盖

主要新增或修改文件：

- `tests/unit/agents/test_decision_agents.py`
- `tests/unit/test_report_exporter.py`
- `tests/integration/test_decision_reporting.py`

新增覆盖：

- 运营方案证据合并和状态降级。
- 标题、五点卖点、关键词和四类客服话术生成。
- 正常方案审校通过。
- 孤立证据编号、虚构百分比和禁止表达被拒绝。
- 低价与高端定位冲突检测。
- 报告版本递增和结构化内容导出。
- 从 Demo 工作流到最终 JSON/Markdown 报告的端到端集成。

## 四、验证结果

### 队友三功能合并时

- `python -m pip check`：通过。
- `python -m pytest -q`：`38 passed`。
- `python -m compileall -q app tests scripts`：通过。
- `python -m ruff check app tests scripts`：通过。
- `python scripts/smoke_test.py`：通过，生成 4 个 Agent 输出、2 条证据和 1 份报告。

### 同步当前远端 main 后再次复核

- `python -m pip check`：通过。
- `python -m pytest -q`：`51 passed`。
- `python -m compileall -q app tests scripts`：通过。
- `python scripts/smoke_test.py`：通过。
- 队友三负责文件的 Ruff 检查：通过。
- 全仓库 Ruff 检查：发现 7 个问题，均来自队友三合并之后新增的队友一文件，涉及导入顺序和
  超过 120 字符的行；队友三文件没有 Ruff 问题。

## 五、未包含内容与原因

- 正式前端：团队文档明确标记为 API 稳定后的后续阶段，本次继续延期。
- Real 模式模型调用和生产 Prompt：当前全局基座仍将 Real/Mock 分析限制在 scaffold 边界。
- PDF 导出和历史版本差异：当前冻结的 `FinalReport` 与 `report_paths` 只定义 JSON/Markdown；
  若要新增 PDF 或版本差异接口，应先提交独立 Contract PR。
- 共享 Schema、API、数据库迁移和 LangGraph 拓扑：均未修改，避免跨团队合同冲突。

## 六、管理员结论

队友三当前阶段后端任务已实现、已测试、已合并并已推送到远端 `main`。不需要再次执行合并。
后续管理员只需关注：正式前端的阶段启动条件，以及当前主分支中队友一新增文件的 7 个 Ruff 告警。
