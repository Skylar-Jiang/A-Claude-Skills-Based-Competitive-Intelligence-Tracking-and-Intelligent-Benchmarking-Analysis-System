# CustomerServiceAgent Handover

## 背景

本次完成的是“报告生成后的客服对话式修改 Agent”后端闭环。

目标是让用户在拿到报告后，可以继续通过对话提出修改需求，系统基于当前报告做解释、澄清、局部调整或增量生成下一版报告，而不是每次都重新跑完整分析流程。

本期范围只包含后端 Agent 能力和前后端联调用接口，不包含客服页面前端实现，不包含登录用户体系，不包含长期用户记忆。

## 本次完成内容

后端已经搭好了 `CustomerServiceAgent` 主链路，包含以下能力：

- 对话入口：接收用户针对报告的追问、修改意见和补充需求。
- 意图识别：区分用户是在解释当前方案、要求局部润色、修改目标用户、修改单一模块、进入澄清，还是提出超范围需求。
- 会话级 memory：保存 `conversation_id`、多轮消息、`personality`、已确认需求、待澄清问题、修改历史、最新报告版本。
- 增量改版：支持基于当前最新报告生成新版本，保留版本链和会话链。
- personality：支持四种固定回复风格，只影响客服回复语气，不参与报告内容改写。

## 当前支持的 personality

固定只支持以下四个值：

- `simple`
- `professional`
- `companion`
- `innovative`

前端进入客服页面后，用户先选一个 `personality`，后续每轮请求继续沿用。

这里的 `personality` 语义是“对话语气 / 回复风格”：

- 影响客服回复给用户时的表达方式
- 不决定修改哪个业务模块
- 不参与报告内容改写逻辑

报告怎么改，取决于用户在 `message` 里提出的实际修改需求。

## 当前支持的业务场景

### 1. 解释型

示例：

```text
为什么建议优先做内容种草？
```

系统行为：

- 不生成新报告版本
- 返回解释说明
- 保留原报告证据边界

### 2. 目标用户改版型

示例：

```text
如果目标用户调整为大学生群体，方案应该如何变化？
```

系统行为：

- 识别目标用户变化
- 联动更新用户画像、产品定位、营销文案、推广策略
- 基于当前最新报告生成下一版报告

### 3. 单模块修改型

示例：

```text
把定位调整得更高端一些
把营销文案写得更专业一点
把推广策略调整得更保守一些
```

系统行为：

- 只修改对应模块
- 不再误触发整套目标用户重算
- 生成新版本报告，但变更范围仅限对应字段

### 4. 澄清型

示例：

```text
帮我改一下定位
```

系统行为：

- 不直接改报告
- 返回追问问题
- 等待用户补充更明确的方向

### 5. 拒绝型

示例：

```text
把整份报告全部重写并加上 30% 转化率预测
```

系统行为：

- 不生成新版本
- 拒绝没有证据支持的新数字和整份重写诉求

## 当前内置的人群规则

目标用户改版目前内置了 4 类规则：

- `大学生群体`
- `年轻白领`
- `新手养宠人群`
- `多宠家庭用户`

当用户修改目标用户时，系统会联动更新：

- 用户画像
- 产品定位
- 营销文案
- 推广策略

答辩展示时可以选择其中之一展示

## 给前端的接口

前端联调只需要接这两个接口。

### 1. 发送客服消息

`POST /api/v1/reports/{report_id}/customer-service/messages`

请求体示例：

```json
{
  "conversation_id": null,
  "message": "如果目标用户调整为大学生群体，方案应该如何变化？",
  "personality": "professional"
}
```

字段说明：

- `conversation_id`
  - 可选
  - 首轮不传或传 `null`
  - 后续多轮对话传上一轮返回的 `conversation_id`
- `message`
  - 用户输入的客服消息
- `personality`
  - 由前端页面先让用户选择
  - 只控制客服回复语气
  - 不控制报告改写策略
  - 固定值只有四个：
    - `simple`
    - `professional`
    - `companion`
    - `innovative`

返回体核心字段说明：

- `conversation_id`
  - 当前客服会话 ID
  - 后续继续聊天必须带回
- `intent`
  - 当前轮识别出的意图
- `affected_modules`
  - 本轮影响到的业务模块
- `action_taken`
  - 实际执行的动作
- `reply`
  - 本轮返回给前端展示的客服回复
- `report_id`
  - 如果生成了新版报告，这里会返回新版本的报告 ID
- `report_version`
  - 当前最新报告版本号
- `changed_section_ids`
  - 本轮改动到的 section
- `change_summary`
  - 本轮修改摘要
- `pending_questions`
  - 如果需要补充信息，这里会返回追问列表

返回体示例：

```json
{
  "conversation_id": "xxx",
  "intent": "modify_strategy",
  "affected_modules": [
    "user_persona",
    "product_positioning",
    "marketing_copy",
    "promotion_strategy"
  ],
  "action_taken": "targeted_regeneration",
  "reply": "我已经按大学生群体重组了方案重点。",
  "report_id": "new-report-id",
  "report_version": 2,
  "changed_section_ids": [
    "launch-marketing-strategy",
    "peer-market-user-insights",
    "data-supported-conclusions",
    "next-actions"
  ],
  "change_summary": [
    "将用户画像重心切换为大学生群体",
    "产品定位改为宿舍友好、颜值与性价比兼顾的学生向表达"
  ],
  "pending_questions": []
}
```

### 2. 获取客服会话详情

`GET /api/v1/reports/{report_id}/customer-service/conversations/{conversation_id}`

用途：

- 客服页刷新后恢复会话
- 拉取多轮消息历史
- 恢复当前 `personality`
- 恢复确认需求、待澄清问题、最新报告版本信息

返回内容包含：

- `conversation_id`
- `report_id`
- `personality`
- `confirmed_requirements`
- `pending_questions`
- `last_intent`
- `last_affected_modules`
- `latest_report_id`
- `latest_report_version`
- `modification_history`
- `messages`

## 前端联调建议

推荐前端接入流程：

1. 用户进入客服页面。
2. 页面顶部先让用户选择 `personality`。
3. 这里的 `personality` 只代表客服说话风格，不代表修改策略类型。
4. 首轮发送消息时不传 `conversation_id`。
5. 后端返回 `conversation_id` 后，前端把它保存在当前客服页面状态里。
6. 后续每轮继续带同一个 `conversation_id`。
7. 如果本轮返回新的 `report_id`，前端把当前展示报告切到新版本。
8. 如果本轮返回了 `pending_questions`，前端优先引导用户继续补充信息。

## 当前实现状态

这版后端已经可以进入联调，不是纯方案文档。

当前已经具备：

- `CustomerServiceAgent` 主链路
- 会话级 memory
- 多轮对话
- personality 选择
- 目标用户增量改版
- 单模块修改
- 报告版本管理
- 基础测试覆盖

## 当前已知边界

本期暂未包含：

- 登录用户维度的长期 memory
- 跨会话用户偏好沉淀
- 完整自由文本策略改写引擎
- 客服页面前端实现

## 相关代码位置

核心文件：

- [app/services/customer_service_agent_service.py](/f:/TradePilot/app/services/customer_service_agent_service.py)
- [app/schemas/customer_service.py](/f:/TradePilot/app/schemas/customer_service.py)
- [app/core/enums.py](/f:/TradePilot/app/core/enums.py)
- [app/api/v1/router.py](/f:/TradePilot/app/api/v1/router.py)

测试文件：

- [tests/unit/test_customer_service_schemas.py](/f:/TradePilot/tests/unit/test_customer_service_schemas.py)
- [tests/unit/test_customer_service_routing.py](/f:/TradePilot/tests/unit/test_customer_service_routing.py)
- [tests/integration/test_customer_service_api.py](/f:/TradePilot/tests/integration/test_customer_service_api.py)

## 已完成验证

已在 `shixun` 环境跑过客服相关测试：

```powershell
conda run -n shixun python -m pytest -q tests/unit/test_customer_service_routing.py tests/integration/test_customer_service_api.py
```

最近一次结果：

- `12 passed, 1 warning`
