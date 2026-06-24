# SESSION.md — 当前工作状态

> 这个文件回答："上次干到哪了、现在在搞什么、有什么临时坑"。
> 跟 TECH_DEBT 的区别：TECH_DEBT 记"欠的债"，SESSION 记"手头的活和临时记忆"。
> 每次开工读它，收工更新它。

## 当前焦点

- **第 1 步收束中**：先清理工作树噪音、修正文档口径，再进入数据库快照审计。当前不做 schema migration，不写真实库。
- **代码验证仍是绿的**：
  - Windows Python: `import holographic` 通过。
  - Windows pytest: `115 passed in 7.01s`。
  - WSL 环境没有 `python`/`pytest` 命令；该项目当前以 Windows Python 作为有效验证入口。
- **实时库口径需要重新核账**：
  - 旧记录曾写到 `2078 active facts / 9 documents`，并基于 `2029 clean facts` 做 Gate A/B。
  - 当前 `reports/scope_gate_audit.md` 显示的是 `333 unique_fact_ids`，明显不是同一口径。
  - 直接用 SQLite `mode=ro` 读取实时 `memory_store.db` 报 `disk I/O error`；`immutable=1` 可粗读主文件，但可能忽略活跃 WAL，不作为最终结论。
  - 因此第 2 步必须先做稳定 DB 快照，再基于快照重新生成 ledger / scope gate 报告。
- **真实库粗读快照（仅供排查，不作最终口径）**：
  - `immutable=1` 粗读主文件：2741 total facts、1051 active facts、1690 soft-deleted facts、9 documents、schema v8。
  - active source 分布粗读：null 29，doc1 227，doc3 47，doc4 77，doc5 46，doc6 258，doc7 14，doc8 240，doc9 113。
  - 这些数字与旧文档不一致，下一步用稳定快照确认。
- **提取 Prompt 已进入事实/废话边界方向**：
  - `_LLMExtractor` 已加入拒收纯互动、临时对话状态、隐喻性劝导、心理动机推断等规则。
  - Doc 9 局部 canary 仍显示需要继续验证“具体性保留”和“口水话拒收”之间的平衡。

## 进行中

- [x] 清理 `SESSION.md` 断裂/重复叙述。
- [x] 识别 CRLF / trailing whitespace 噪音。
- [ ] 完成第 1 步提交。

## 下一步顺序

1. 第 1 步：清理工作树噪音和文档口径，提交一个 git checkpoint。
2. 第 2 步：做稳定 DB 快照审计，输出当前事实 ledger。
3. 第 3 步：基于真实 canary 修提取边界和 dirty fact 处理。
4. 第 4 步：实现批量 retain 的延迟 category bank 重建。

## 已知陷阱（临时）

- `project` category 仍然过宽，HRR category bank 曾出现 SNR 过载；在第 2 步快照审计前不要把旧 SNR 数字当当前结论。
- 当前 reports 目录包含多轮脚本产物，不能默认 `reports/scope_gate_audit.md` 就是最新全库报告。
- 不要直接在活 WAL 库上做结论性审计；先快照，再读快照。
- 事实/对话噪音仍是主风险：提取器要拒收问安、睡觉提醒、聊天节奏、临时隐喻和心理归因，只保留长期可召回的事实、规约、客观结论和明确建议。

## 决策记录

- **scope 不可逆门**：在稳定快照和人工复核完成前，不新增 `facts.scope`、`fact_scopes` 或 provenance migration。
- **source_doc_id 边界**：`source_doc_id` 是单值归属，不是完整 provenance；发生 merge 后不能用它推导完整来源。
- **事实/废话判定边界规则**：LLM 提取 Prompt 必须做客观的“事实/对话噪音”判定，拒收纯互动、聊天状态描述、劝慰和隐喻性表述。
- **生产库测试场纪律**：任何会写真实 `memory_store.db` 的动作都必须先备份，并把 backup 用作前后 diff 基准。
- **P2 图边仍保持否决状态**：除非新的真实快照证明 entity fan-out 明显回升，否则不重启 shared-entity 图边。

---

*Last updated: 2026-06-24*
