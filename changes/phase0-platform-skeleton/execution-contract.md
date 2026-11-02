# 执行合同 — phase0-platform-skeleton（Legacy Full）

> 本文件是既有 legacy 任务收尾所需的合同记录。实现、评审与测试均已在 2026-10-16/17 完成（见 `progress.md` 与 `.superpowers/sdd/reviews/`），此处只把已批准的规划工件固化成一份可核对的执行握手，不改变范围、不引入新工作。

## Intent Lock

- **问题与范围**：按 [proposal.md](proposal.md) 与 `specs/platform-core/spec.md`，交付求职平台的 Phase 0 基座——多用户账号体系（邀请码注册 + JWT）、每用户 BYOK 模型接入、统一 LLM 网关与调用记账、岗位手动导入（共享/私有双轨）、简历上传与脱敏结构化解析。这是后续采集（Phase 3/4）与匹配打分（Phase 1）共同依赖的地基。
- **范围外**：岗位自动采集、人岗匹配打分、简历修改建议（Phase 1-4）；账单/额度计费；移动端与主题化 UI。

## Approved Behavior

| 需求 / 场景引用 | 任务 ID | 验证证据 |
|---|---|---|
| `specs/platform-core/spec.md` → Requirement: 邀请码注册与认证（含「首用户引导」「邀请码一次性」Scenario） | 2, 3 | `tests/test_auth_admin.py::test_first_user_becomes_admin`、`test_invitation_single_use`、`test_revoked_invitation_rejected`、`test_non_admin_cannot_access_admin` |
| Requirement: 每用户模型接入（「key 永不回显」「用户隔离」） | 4, 5 | `tests/test_providers.py::test_create_masks_key_everywhere`、`test_provider_isolation_between_users` |
| Requirement: 统一 LLM 网关（「坏输出恢复」「三次全败」） | 5 | `tests/test_llm_gateway.py`（重试三态、记账、默认模型回退） |
| Requirement: 岗位手动导入（「双轨落表」「失败重试」） | 6, 7 | `tests/test_jobs.py`（共享/私有落表、content_hash、失败重试） |
| Requirement: 简历导入与脱敏解析（「出站脱敏」「master 唯一」） | 8, 9 | `tests/test_resumes.py`（PDF/DOCX/MD 抽取、脱敏出站断言、master 唯一、用户隔离） |
| Requirement: 成本记账（「汇总隔离」） | 10 | `tests/test_costs`（`test_llm_gateway.py` 内汇总隔离断言） |

行为变化：无。所有 Requirement 均由既有实现与测试覆盖，无未映射需求。

## Design Constraints

引用 [design.md](design.md)：同步 SQLAlchemy + Alembic（12 表）；测试缝合点为 HTTP API；`llm_gateway._invoke` 是唯一的模型调用桩位（测试全 mock）；scrypt 口令散列 + JWT 会话 + Fernet 加密落库；provider 解析取首个 enabled 并支持任务级模型覆盖；简历两遍脱敏（身份抽取 → 正则/姓名替换）；首用户免邀请码自动 admin；岗位双表同构 + 多态引用。

## Execution Plan

计划文件：`.superpowers/sdd/execution-plan.json`（revision 3）。审查证据：`.superpowers/sdd/reviews/snapshots/`。

### Execution Waves

- 单波次 `implementation`（serial，tasks 1-10），已完成；集成边界仅两处：LLM 网关（对外只暴露 `chat_structured`）与任务运行器（Phase 1 换 arq 时保持签名不变）。
- **执行方式**：Native `inline`。
- **审查策略**：`final`（一次全量审查）。
- **边界与理由**：Phase 0 为单一内聚基座，无独立可并行部署单元，故不拆波次、不派发子代理。

## Test Obligations

- **行为回归与边界**：`backend/tests/` 覆盖认证/权限矩阵、provider 掩码与隔离、网关重试与记账、岗位双轨落表与重试、简历三格式解析与脱敏、master 唯一、成本汇总隔离。
- **任务级验证**：受影响测试文件按任务聚焦运行。
- **集成 / 最终验证**：`cd backend && .venv\Scripts\python.exe -m pytest -q`（34 passed）；`alembic upgrade head` 空库建 12 表；`npm run build` 通过。

## Review Gates

- **final**：已完成一次全量审查（`snapshots/ae79a06b-f290-4560-8c9d-9d90f7fc789e.md`，verdict=pass，816c090）；收尾时对 2edd653→e873d41 全范围补记回执（`snapshots/b1a7c3d2-5f4e-4a61-9c2b-7d0e8f3a1b62.md`，verdict=pass），代码层零改动。
- Critical/Important 发现均有修复提交与回归测试锚定，见 final review 的「审查发现与处置」。

## Escalation Rules

- 范围变化回到 specifying；契约偏移回到 bridging。
- 非语义修正走 resync 并保留失败链；语义变更需重新批准后 revise。
- 遗留风险不在本范围内闭环：litellm 真实出站未测（无真实 key）、compose web 镜像未在本机构建。

## Approval

- DP-3：`pass`（2026-10-27T15:16:06.171Z 记录）。
- DP-4：`inline: plan revision 2; user-confirmed-revision`（2026-10-27T15:24:44.365Z）。
- 本次收尾：仅重建执行计划格式（revision 3）并补记全范围审查回执，用户已确认「先把 Phase 0 收尾，再开 Phase 1」。
