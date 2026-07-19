# CustomerServiceAgent 后端接口实施计划

> **运行环境要求：** 本计划中的开发、测试、脚本执行均默认在 `shixun` 虚拟环境中进行。
> 建议先执行 `conda run -n shixun python --version` 或激活对应环境后再开始实施。

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**目标：** 在不依赖前端具体实现的前提下，为现有报告系统补齐一个面向前端的客服式对话接口，让用户可以围绕报告继续提问、提出修改意见，并获得增量更新后的方案结果。

**架构思路：** 保留现有分析工作流、报告导出、不可变版本控制和 `report support` 能力，在其上新增一个 `CustomerServiceAgent` 编排层。前端只调用一个客服对话接口，后端负责识别用户意图，并决定走“解释说明”“局部改写”“定向增量重算”还是“澄清问题”分支。

**技术栈：** FastAPI、Pydantic v2、SQLAlchemy、现有 LangGraph/LangChain Agent 体系、pytest

---

## 一、当前项目现状梳理

### 1. 前端现状

- `frontend/` 目录目前基本为空，只有 `.gitkeep`
- 因此前阶段不应依赖前端页面细节
- 当前最合理的分工是：后端先把客服对话 API 和返回结构定义稳定，前端后续直接接入

### 2. 后端已有可复用能力

当前后端已经具备以下基础能力：

- `POST /api/v1/analysis-runs/{run_id}/feedback`
  - 可记录用户对分析结果的反馈文本
- `POST /api/v1/reports/{report_id}/support`
  - 支持对单个报告区块执行 `explain` 或 `edit`
- `GET /api/v1/reports/{report_id}/versions`
  - 可查看报告所有不可变版本
- `POST /api/v1/reports/{report_id}/rollback`
  - 可从历史版本生成新的最新版本
- `GET /api/v1/conversations/{session_id}`
  - 可读取对话历史

### 3. 当前缺失的核心能力

目前还没有真正意义上的客服 Agent 闭环，缺少以下能力：

- 没有 `CustomerServiceAgent`
- 没有统一的客服对话入口，前端无法只接一个接口完成闭环
- 没有“理解用户修改意图并自动识别影响模块”的逻辑
- 没有结构化维护“已确认需求、待澄清问题、用户偏好回复风格、修改历史”的会话状态
- 没有“局部增量更新报告”的客服编排层，只存在底层 `support` 能力

---

## 二、本次实施范围

本次计划只做后端，不做前端页面。

### 目标范围

- 新增客服式对话接口
- 支持围绕报告进行多轮修改
- 支持维护会话上下文
- 支持根据用户意图，对指定模块做增量更新
- 支持不同回复风格
- 支持输出“修改说明 + 更新后的结果 + 新报告版本信息”

### 非目标范围

- 不重做整套前端
- 不改动现有完整分析工作流主链路
- 第一阶段不做“全报告任意改写”
- 不做脱离证据约束的自由生成

---

## 三、客服 Agent 的业务目标

围绕下面这条业务闭环落地：

`方案生成 -> 用户反馈 -> Agent 理解意图 -> 增量优化 -> 更新报告 -> 返回修改说明`

典型用户输入示例：

- “如果目标用户调整为大学生群体，方案应该如何变化？”
- “这部分营销文案太普通了，换成更专业一点的表达。”
- “为什么你建议优先做内容种草？”
- “推广策略里短视频渠道不够具体，帮我补充一下。”

系统需要能识别这些输入分别属于：

- 解释型
- 文案调整型
- 模块修改型
- 需要澄清型
- 超出支持范围型

---

## 四、建议新增的后端接口

### 1. 客服消息发送接口

建议新增：

- `POST /api/v1/reports/{report_id}/customer-service/messages`

#### 请求体建议

```json
{
  "conversation_id": "optional-conversation-id",
  "message": "如果目标用户调整为大学生群体，方案应该如何变化？",
  "personality": "professional"
}
```

#### 字段说明

- `conversation_id`
  - 可选
  - 首轮不传，由后端生成
  - 多轮对话继续传同一个 ID
- `message`
  - 用户输入内容
- `personality`
  - 可选
  - 用于控制回复风格

#### personality 建议枚举

- `simple`
  - 简洁通俗型
- `professional`
  - 专业严谨型
- `companion`
  - 耐心陪伴型
- `innovative`
  - 创新启发型

### 2. 客服对话详情接口

建议新增：

- `GET /api/v1/reports/{report_id}/customer-service/conversations/{conversation_id}`

用于前端获取该报告对应的客服会话详情，包括：

- 消息历史
- 当前已确认需求
- 待澄清问题
- 最近一次修改影响的模块
- 最近一次生成的新报告版本

---

## 五、客服接口响应建议

建议统一返回以下结构：

```json
{
  "conversation_id": "conv-1",
  "intent": "modify_strategy",
  "affected_modules": [
    "user_persona",
    "product_positioning",
    "marketing_copy",
    "promotion_strategy"
  ],
  "action_taken": "targeted_regeneration",
  "reply": "已根据大学生群体重新调整用户画像、产品定位、营销文案和推广策略。",
  "report_id": "report-2",
  "report_version": 2,
  "changed_section_ids": [
    "target-segments",
    "launch-marketing-strategy"
  ],
  "change_summary": [
    "用户画像调整为大学生人群",
    "定位改为高性价比、宿舍友好型",
    "文案强调社交传播与颜值表达",
    "渠道策略增加校园场景传播"
  ],
  "pending_questions": []
}
```

### 核心字段建议

- `intent`
  - 当前用户意图
- `affected_modules`
  - 本轮影响的业务模块
- `action_taken`
  - 本轮后端实际采取的动作
- `reply`
  - 返回给用户的客服话术
- `report_id`
  - 当前最新报告 ID
- `report_version`
  - 当前最新版本号
- `changed_section_ids`
  - 变更区块
- `change_summary`
  - 变更摘要
- `pending_questions`
  - 若信息不足，需要返回澄清问题

---

## 六、模块影响映射规则

建议先用规则驱动，优先保证稳定性，而不是一开始就完全依赖大模型自由判断。

### 1. 用户修改目标用户

例如：

- “目标用户改成大学生”
- “面向年轻白领而不是家庭主妇”

建议影响模块：

- `user_persona`
- `product_positioning`
- `marketing_copy`
- `promotion_strategy`

### 2. 用户修改产品定位

例如：

- “定位改成高端一点”
- “更偏功能型，不要太情绪化”

建议影响模块：

- `product_positioning`
- `marketing_copy`
- `promotion_strategy`

### 3. 用户修改营销文案

例如：

- “文案更专业一点”
- “语气更适合学生”

建议影响模块：

- `marketing_copy`

### 4. 用户修改推广策略

例如：

- “增加校园渠道”
- “短视频部分更具体一点”

建议影响模块：

- `promotion_strategy`

### 5. 用户只是提问原因

例如：

- “为什么建议先做内容种草？”

建议动作：

- 走 `explain`

### 6. 用户表达不清晰

例如：

- “帮我改一下定位”

建议动作：

- 走 `clarification_required`
- 返回待补充问题

---

## 七、建议新增的后端分层设计

### 1. Schema 层

新增：

- `app/schemas/customer_service.py`

建议包含：

- `CustomerServiceMessageRequest`
- `CustomerServiceMessageResponse`
- `CustomerServiceConversationRead`
- `CustomerServiceIntent`
- `CustomerServicePersonality`

### 2. Service 层

新增：

- `app/services/customer_service_agent_service.py`

职责：

- 接收客服消息
- 加载当前报告
- 识别用户意图
- 判定影响模块
- 决定调用：
  - `ReportSupportService._explain`
  - `ReportSupportService._edit`
  - 或定向增量重算逻辑
- 写入 conversation 状态
- 返回统一结果

### 3. Agent 层

可选新增：

- `app/agents/customer_service.py`

第一阶段可以先不用复杂 Agent 编排。

建议策略：

- 第一版先用“规则 + 小范围模板化生成”
- 第二版再逐步引入真正的多轮客服 Agent 推理

### 4. Router 层

修改：

- `app/api/v1/router.py`

新增两个接口：

- `POST /api/v1/reports/{report_id}/customer-service/messages`
- `GET /api/v1/reports/{report_id}/customer-service/conversations/{conversation_id}`

---

## 八、会话状态建议如何保存

现有 `Conversation` 和 `Message` 模型可以复用，但元数据需要扩展。

建议在 `conversation.metadata_json` 中维护：

- `kind`
  - 固定为 `customer_service`
- `run_id`
- `report_id`
- `personality`
- `confirmed_requirements`
  - 已确认需求
- `pending_questions`
  - 待澄清问题
- `last_intent`
- `last_affected_modules`
- `latest_report_id`
- `latest_report_version`
- `modification_history`

建议在 `message.metadata_json` 中记录：

- `intent`
- `action_taken`
- `affected_modules`
- `changed_section_ids`
- `audit_decision`
- `result_report_id`
- `result_report_version`

这样后续前端要恢复会话状态时，不需要自己做复杂拼装。

---

## 九、报告更新策略建议

第一阶段不要做整份报告重跑，而是只做受控的增量更新。

### 第一阶段建议只支持以下模块增量更新

- 用户画像
- 产品定位
- 营销文案
- 推广策略

### 更新方式建议

#### 方式 A：复用现有 `support edit`

适用于：

- 文案润色
- 小范围语气改写
- 单个 section 的受控替换

#### 方式 B：新增“定向增量重算”

适用于：

- 用户画像变化
- 产品定位变化
- 推广策略变化

具体做法：

- 不重跑整个分析工作流
- 基于当前报告、原始分析结果、已有 evidence 和用户新需求，只重算目标 section
- 生成新的不可变版本

### 必须保留的约束

- 不允许捏造证据
- 不允许引入未经支持的新数字
- 不允许把 peer review 误写成新商品真实用户反馈
- 不允许整份报告无限制重写

---

## 十、实施任务拆分

### 任务 1：定义客服接口 Schema

**涉及文件：**

- 新建 `app/schemas/customer_service.py`
- 修改 `app/schemas/api.py`
- 视需要修改 `app/core/enums.py`
- 新建 `tests/unit/test_customer_service_schemas.py`

**目标：**

- 定义请求响应结构
- 固定 personality 和 intent 取值
- 让前端尽早对接稳定 contract

**完成标准：**

- 可以正确校验 `message`、`conversation_id`、`personality`
- 返回结构包含：
  - `intent`
  - `affected_modules`
  - `action_taken`
  - `reply`
  - `report_id`
  - `report_version`
  - `changed_section_ids`
  - `change_summary`
  - `pending_questions`

---

### 任务 2：扩展 conversation 状态存储

**涉及文件：**

- 修改 `app/services/conversation_service.py`
- 必要时修改 `app/db/models/core.py`
- 需要时补 migration
- 新建 `tests/integration/test_customer_service_conversation_state.py`

**目标：**

- 支持保存客服会话的上下文状态

**完成标准：**

- 能保存 personality
- 能保存已确认需求
- 能保存待澄清问题
- 能保存最近一次影响模块
- 能保存最新报告版本

---

### 任务 3：实现 CustomerServiceAgent 编排服务

**涉及文件：**

- 新建 `app/services/customer_service_agent_service.py`
- 可选新建 `app/agents/customer_service.py`
- 修改 `app/services/report_support_service.py`
- 新建 `tests/integration/test_customer_service_agent_service.py`

**目标：**

- 建立统一客服处理入口

**核心职责：**

- 识别用户意图
- 判断影响模块
- 选择执行路径：
  - `explain`
  - `localized_edit`
  - `targeted_regeneration`
  - `clarification_required`
  - `reject`

**完成标准：**

- 用户问原因时，能走 explain
- 用户润色文案时，能走 edit
- 用户修改目标用户时，能触发定向增量更新
- 用户表达模糊时，能返回澄清问题

---

### 任务 4：暴露前端可调用的客服接口

**涉及文件：**

- 修改 `app/api/v1/router.py`
- 修改或复用 `app/schemas/api.py`
- 修改 `tests/contract/test_api.py`
- 新建 `tests/integration/test_customer_service_api.py`

**目标：**

- 让前端只接一组客服接口即可完成闭环

**完成标准：**

- OpenAPI 中出现新路由
- 新接口使用统一 envelope
- 接口可返回完整客服响应结构
- 会话详情接口可返回结构化历史

---

### 任务 5：补齐文档

**涉及文件：**

- 修改 `docs/api-contract.md`
- 修改 `docs/frontend-integration.md`
- 修改 `docs/report-support.md`
- 可新增 `docs/customer-service-api.md`

**目标：**

- 让前端和后端对齐接口使用方式

**完成标准：**

- 文档写清请求体
- 写清返回体
- 写清 personality 取值
- 写清哪些请求会生成新报告版本

---

## 十一、客服测试模块

这一部分直接作为本计划的测试实施说明。

### 1. 测试总原则

客服功能测试继续沿用项目现有测试分层，不单独发明新流程。

仍然遵守仓库已有基础门禁：

```powershell
python -m pip check
python -m pytest -q
python -m compileall -q app tests scripts
python -m ruff check app tests scripts
python scripts\smoke_test.py
```

在此基础上，为客服功能补 4 层测试。

### 2. Contract Test

**目的：**

- 确保前端可依赖的接口 contract 稳定

**建议覆盖内容：**

- 新接口是否出现在 `/openapi.json`
- 是否继续使用统一 `success/data/meta/error` 响应包裹
- 请求体字段是否完整
- 返回体字段是否完整

**建议修改文件：**

- `tests/contract/test_api.py`

**至少校验以下路由：**

- `/api/v1/reports/{report_id}/customer-service/messages`
- `/api/v1/reports/{report_id}/customer-service/conversations/{conversation_id}`

### 3. Unit Test

**目的：**

- 测试最小逻辑单元，避免把所有问题都压到集成测试里

**建议新增测试文件：**

- `tests/unit/test_customer_service_schemas.py`
- `tests/unit/test_customer_service_routing.py`

**重点测试内容：**

- personality 枚举校验
- request/response schema 校验
- intent 分类规则
- affected modules 映射规则

**建议重点断言：**

- “解释一下为什么建议先做内容种草” -> `explain`
- “把目标用户改成大学生” -> `targeted_regeneration`
- “把语气写得更专业一点” -> `localized_edit`
- “帮我改一下定位” -> `clarification_required`

### 4. Integration Test

**目的：**

- 测试客服接口的完整业务闭环

**建议新增测试文件：**

- `tests/integration/test_customer_service_api.py`
- `tests/integration/test_customer_service_conversation_state.py`

**必须覆盖的 5 类主路径：**

#### 场景 1：解释型

用户输入：

- “为什么建议优先做内容种草？”

预期：

- `action_taken=explain`
- 不创建新报告版本
- conversation 里记录 user/assistant 消息

#### 场景 2：局部改写型

用户输入：

- “这段营销文案改得更专业一点”

预期：

- `action_taken=localized_edit`
- 只修改局部 section
- `report_version + 1`
- `changed_section_ids` 正确

#### 场景 3：增量重算型

用户输入：

- “如果目标用户调整为大学生群体，方案应该如何变化？”

预期：

- `action_taken=targeted_regeneration`
- `affected_modules` 至少包含：
  - `user_persona`
  - `product_positioning`
  - `marketing_copy`
  - `promotion_strategy`
- 生成新报告版本
- 返回修改摘要

#### 场景 4：澄清型

用户输入：

- “帮我改一下定位”

预期：

- `action_taken=clarification_required`
- 返回 `pending_questions`
- 不生成新报告版本

#### 场景 5：拒绝型

用户输入：

- “把整份报告全部重写并加上 30% 转化率预测”

预期：

- 返回拒绝或 validation error
- 不生成新版本
- 对话历史仍然保留

### 5. Smoke Test

**目的：**

- 做一条本地可快速执行的验收链路

**建议新增脚本：**

- `scripts/customer_service_smoke.py`

**建议流程：**

1. 创建一个 demo 产品
2. 发起分析并拿到 `report_id`
3. 调用客服消息接口发送一条修改请求
4. 校验：
   - 返回 `conversation_id`
   - 返回 `action_taken`
   - 如果是增量修改，则 `report_version` 增加
   - `changed_section_ids` 合理
   - 拉取 conversation detail 时能看到完整会话历史

### 6. 客服功能上线前最低测试要求

建议把下面这些作为最小上线门槛：

- `tests/contract/test_api.py` 已覆盖客服新接口
- `tests/unit/test_customer_service_schemas.py` 通过
- `tests/unit/test_customer_service_routing.py` 通过
- `tests/integration/test_customer_service_api.py` 通过
- `tests/integration/test_customer_service_conversation_state.py` 通过
- `python -m pytest -q` 全量通过
- `python scripts/customer_service_smoke.py` 本地通过

### 7. 推荐测试执行顺序

开发时建议这样跑，效率最高：

1. 先写并跑 contract test
2. 再写并跑 unit test
3. 再写并跑 integration test
4. 最后补 smoke script
5. 合并前执行一次全量 `python -m pytest -q`

---

## 十二、建议的落地节奏

### 里程碑 A

- 定义 Schema
- 定义新接口 contract
- 前端可以先按 contract 开始联调准备

### 里程碑 B

- 接通 explain / edit 到统一客服入口
- 跑通多轮 conversation

### 里程碑 C

- 实现“目标用户 / 定位 / 文案 / 推广策略”四类模块的定向增量更新

### 里程碑 D

- 补文档
- 补 smoke
- 跑通完整测试链路

---

## 十三、实施建议

- 第一版优先做稳定、可测、可接入，不要一开始追求特别智能
- 意图识别第一版建议规则优先，大模型辅助
- 报告更新第一版建议只更新少量受控 section
- 所有修改都继续复用当前不可变版本体系
- 前端后续最好只接新的客服接口，不直接拼接 `support`、`feedback`、`conversation` 多个底层接口

---

Plan complete and saved to `docs/plans/2026-07-19-customer-service-agent-api.md`. Two execution options:

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

Which approach?
