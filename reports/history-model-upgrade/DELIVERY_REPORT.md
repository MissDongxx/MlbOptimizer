# 交付报告

## 基线核验

- 用户附件：`MlbOptimizer-full-history-model-upgrade.zip`
- 实测 bytes：2,733,040
- 实测 SHA-256：`6093eb16d9bba4b55b0ad0e19993c508d8ec0b73f3dfcc1124d23f09eafa5f06`
- 用户声明 Git HEAD：`5f356365725b1def066b981fed3aa5558bb06522`
- 附件不含 `.git`，因此无法从附件本地重新证明 HEAD 或区分已提交与未提交文件。本轮累计 patch 以附件解压树为基线生成，不伪造 Git 状态。

## 实际实现

新增完整 pipeline package，包含配置、registry、qualification、dataset、modeling、cycle 和 CLI。扩展 backtest runner 支持 registry qualification hash 绑定与 additive candidate model 方法。Scheduler import 改为可选，以隔离缺 APScheduler 环境对非 scheduler 测试的影响。NumPy 被列为 ridge 的直接依赖并同步到 lock metadata。

关键修复包括：

- registry 状态机、原子写入、不可变 artifact、hash 复核、字节级幂等
- 同 root 并发 cycle fail-closed 锁
- 显式 provider Game Set 证据验证与受审计 false-to-true 升级
- direct upload 与 salary capture inbox
- StatsAPI retry/cache/offline/full-pool actuals/DNP/identity audit 编排
- qualified-only deterministic baseline backtest
- event-time-safe dataset
- hitter/pitcher deterministic ridge、fixed chronological holdout、expanding walk-forward
- promotion gate、model artifact、model card、promotion report
- candidate_model 第四回测方法，保留 random/legacy/optimized
- CLI 与可被外部调度器调用的单次命令

## 测试结果

- 新增 pipeline 测试：19 passed
- 全量回归：131 passed in 20.27s
- `pytest --collect-only`：131 tests collected
- Ruff 未运行成功，因为受控环境未安装 ruff 且内部 package index 无法解析项目依赖
- `uv lock --check` 与 `uv sync --locked --extra dev` 未运行成功，原因是当前内部 package index 找不到已声明并已锁定的 APScheduler。原始输出保留在 `ENVIRONMENT_TOOLING.log`

## 离线 cycle

示例使用仓库 StatsAPI cache 和 fixture feature，实际完成：

- 2 场 final game feed 离线命中
- 21/21 full-pool actuals
- 20 played + 1 DNP=0 且有证据
- identity ambiguous=0、unresolved=0
- registry artifact verify PASS

严格门禁随后正确拒绝该 slate，因为它是 `data_kind=fixture` 且 provider Game Set 未验证。Baseline backtest 与模型均 NOT_EVALUATED，promotion status 为 `REJECTED_NOT_EVALUATED`。该结果只证明自动化路径，不构成真实历史效果。

## 残余风险与明确阻塞

1. 附件内没有满足全部资格门禁的多日真实非等薪 DK Classic 历史池，因此不能给出优化器或模型性能结论。
2. 合法获得 DraftKings 私有历史 pool 的来源仍未解决。系统不会绕过该限制，也不会抓取私有历史数据。
3. 真正长期验证必须从未来赛前真实上传开始积累，并保留 provider/DraftGroup 证据、raw source、捕获时间和最终 StatsAPI feeds。
4. 当前受控 package index 的 APScheduler 缺失属于执行环境问题。项目声明与 lock 保留该依赖，正常 package index 环境需由 Codex 独立执行 `uv sync --locked --extra dev`。
5. `PROMOTION_ELIGIBLE_CANDIDATE` 即使未来出现，也不等于允许部署，仍需独立审查、真实样本门槛和生产变更流程。

## 未执行事项

未 commit、未 push、未 deploy、未创建或修改线上任务、未修改生产配置、未迁移 DB、未访问用户数据、未把 fixture 计为真实验证。
