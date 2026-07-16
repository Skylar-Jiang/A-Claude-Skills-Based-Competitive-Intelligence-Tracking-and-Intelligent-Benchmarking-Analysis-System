# MiniMax-M3 四 Agent 兼容性修复与验证报告

## 结论

在分支 `fix/minimax-m3-agent-compatibility` 上完成兼容性修复后，TradePilot 的四个 Agent 已使用 MiniMax-M3 中国区真实 API 完成 3 轮不同商品场景测试。3 轮均满足以下功能通过标准：

- ProductMarketAgent、UserInsightAgent、OperationsDecisionAgent 状态均为 `succeeded`；
- EvidenceAuditAgent 完成真实模型调用且状态不为 `rejected`；
- 四个 Agent 的 `implementation_status` 均为 `production`；
- 每个 Agent 每轮至少完成 1 次真实模型调用；
- 结构化输出均通过 `PydanticOutputParser`；
- 每轮均成功生成 JSON 和 Markdown 报告。

审校 Agent 在 3 轮中均返回 `warning`，原因是受控测试证据仅包含 1 个同类商品和 2 条评论，以及运营内容中的待验证数值占位符。这说明审校功能正常拦截了证据不足和内容风险，不代表 Agent 调用失败。

## 分支与测试范围

- 分支：`fix/minimax-m3-agent-compatibility`
- 基线提交：`66b26da`（`feat: complete backend excellence gates`）
- 测试日期：2026-07-16
- API 区域：中国区
- OpenAI 兼容地址：`https://api.minimaxi.com/v1`
- 模型：`MiniMax-M3`
- 测试方式：本地直接执行四 Agent 串联调用，使用受控商品、同类商品和评论证据；调用是真实模型调用，测试证据不是线上完整市场数据。
- 密钥处理：密钥仅在测试进程内以环境变量加载，未写入代码、报告、日志、`.env` 或 Git 提交。

## 修改了什么

### 1. 为 MiniMax-M3 结构化输出关闭 thinking

修改 `app/agents/model_factory.py`：

- 新增 `_analysis_extra_body`，集中生成分析模型的供应商专用请求参数；
- 当 `OPENAI_BASE_URL` 指向 MiniMax 中国区或国际区，且模型名以 `MiniMax-M3` 开头时，发送：

  ```json
  {"thinking": {"type": "disabled"}}
  ```

- 保留原有 DeepSeek 关闭 thinking 的行为；
- 普通 OpenAI 兼容模型不会收到 MiniMax 专用参数，避免影响其他供应商。

### 2. 明确运营 Agent 的 `positioning` 类型约束

修改 `app/agents/operations_decision.py`：

- 在系统提示词中明确要求 `positioning` 必须是单个普通字符串，不能是对象或数组；
- 保留现有严格后处理和解析重试机制，不通过宽松强制转换掩盖错误结构。

### 3. 增加模型工厂回归测试

修改 `tests/unit/agents/test_model_factory.py`：

- 验证 MiniMax-M3 会收到关闭 thinking 的请求参数；
- 验证 JSON response format 仍然启用；
- 验证通用 OpenAI 兼容供应商不会收到 MiniMax 专用参数；
- 原有 DeepSeek 和 Qwen 行为继续由既有测试覆盖。

### 4. 提交真实生成的 Markdown 样例

本目录包含三份真实模型链路生成的脱敏报告：

- `dog-harness-report.md`
- `cat-fountain-report.md`
- `travel-mug-report.md`

## 为什么要修改

MiniMax-M3 在 OpenAI 兼容接口中默认开启 thinking。项目要求模型只返回受约束的 JSON，但默认 thinking 会带来两个实际问题：

1. 推理 token 占用 `max_tokens`，项目默认 `4096` 时，最终 JSON 可能尚未完成就被截断；
2. 推理内容与最终 JSON 同处于响应 `content` 时，推理中的花括号会干扰项目的 JSON 对象提取，导致 `JSONDecodeError`。

MiniMax 官方 OpenAI 兼容文档说明 MiniMax-M3 支持通过 `thinking.type=disabled` 关闭 thinking，适合当前这种有界结构化 JSON 场景：<https://platform.minimax.io/docs/api-reference/text-openai-api>。

关闭 thinking 后，猫饮水机场景又暴露出 `positioning` 类型不稳定：模型连续返回对象而不是字符串。项目已经有严格校验与一次解析重试，但提示词没有明确该字段的类型。增加明确约束后复测通过，同时保留了原有严格校验边界。

## 修复前失败证据

| 阶段 | 配置 | 结果 | 主要错误 |
| --- | --- | --- | --- |
| 首轮，3 个场景 | thinking 默认开启，`max_tokens=4096` | 0/3 完成 | 3 次 `LengthFinishReasonError`，推理占满输出预算 |
| 第二轮，3 个场景 | thinking 默认开启，`max_tokens=8192` | 0/3 完成 | 3 次 `JSONDecodeError`，推理内容干扰 JSON 提取 |
| 关闭 thinking 后首轮 | `max_tokens=4096` | 2/3 完成 | 猫饮水机场景 `positioning` 连续返回对象，解析重试后仍失败 |
| 增加字段类型约束后 | `max_tokens=4096` | 3/3 完成 | 无功能错误 |

## 最终三轮真实调用结果

| 场景 | 商品市场 | 用户洞察 | 运营决策 | 证据审校 | 模型调用 | 解析重试 | 总 token | 总耗时 | Markdown |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 犬用胸背带 | succeeded | succeeded | succeeded | warning | 4 | 0 | 17,633 | 81.149 秒 | 已生成 |
| 猫咪饮水机 | succeeded | succeeded | succeeded | warning | 4 | 0 | 17,369 | 92.606 秒 | 已生成 |
| 旅行保温杯 | succeeded | succeeded | succeeded | warning | 4 | 0 | 20,109 | 112.838 秒 | 已生成 |
| 合计 | 3/3 | 3/3 | 3/3 | 3/3 已完成 | 12 | 0 | 55,111 | 286.593 秒 | 3 份 |

### 按 Agent 汇总

| Agent | 成功轮次 | 模型调用 | 总 token | 总耗时 |
| --- | ---: | ---: | ---: | ---: |
| ProductMarketAgent | 3/3 | 3 | 8,541 | 74.194 秒 |
| UserInsightAgent | 3/3 | 3 | 9,712 | 106.713 秒 |
| OperationsDecisionAgent | 3/3 | 3 | 20,693 | 52.111 秒 |
| EvidenceAuditAgent | 3/3 | 3 | 16,165 | 53.575 秒 |

所有最终成功调用的 `model_call_count` 均为 1，`parse_retry_count` 均为 0。

## 审校 warning 说明

测试刻意使用小规模受控证据，便于验证证据绑定和审校边界：每个场景只有 1 个同类父 ASIN、1 条正向评论和 1 条低评分评论。因此审校 Agent 正确报告了以下风险：

- 样本量不足以支撑“集中”“高度同质化”等分布性结论；
- 新品缺少尺寸、容量、耐久性等待上市验证参数；
- 部分运营步骤含“待验证数值”占位符，不能直接用于发布；
- 唯一同类商品价格不足以代表完整市场价格带。

这些 warning 证明 EvidenceAuditAgent 的风险识别路径已执行。三份报告不应作为真实上市决策直接发布，需接入更完整的同类商品和评论数据后再次审校。

## 自动化质量检查

| 检查 | 结果 |
| --- | --- |
| `python -m pytest -q` | 156 passed，3 skipped |
| `python -m ruff check .` | 通过 |
| `tests/unit/agents/test_model_factory.py` | 4 passed |
| `tests/unit/agents/test_decision_agents.py` | 8 passed |
| `mypy app` | 未执行：当前虚拟环境未安装 mypy，且项目现有质量命令未配置 mypy |

## 建议合并理由

本修改范围小且有明确的真实失败证据：只为 MiniMax-M3 增加官方支持的 thinking 控制参数，并加强一个结构化字段的提示词约束。通用 OpenAI 兼容供应商行为由新增测试保护，完整后端测试与 Ruff 均通过，建议由管理员审阅后合并到 `main`。
