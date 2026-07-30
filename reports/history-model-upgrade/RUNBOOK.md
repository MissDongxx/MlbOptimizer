# 运行手册

## 1. 安装与环境

推荐 Python 3.12 或项目支持版本，并使用仓库锁文件：

```bash
cd backend
uv sync --locked --extra dev
```

本次受控容器的内部 package index 缺少已声明的 APScheduler，因此 `uv lock --check` 和 `uv sync --locked --extra dev` 无法完成。具体原始输出见 `ENVIRONMENT_TOOLING.log`。测试使用容器已预装依赖运行。Scheduler 模块已改为惰性导入，非 scheduler 的 CLI 和测试不再因环境缺 APScheduler 而无法收集；真正调用 `start_scheduler()` 时仍会明确报依赖缺失。

## 2. 配置

复制并修改：

```bash
cp backtest/pipeline.example.json backtest/pipeline.local.json
```

重要配置：

- `root_dir`：全部 runtime 工件根目录
- `offline`：true 时严格只读 StatsAPI cache
- `retries`、`timeout_seconds`：在线请求重试
- `seed`、`lineups_per_method`：所有方法共用
- `min_backtest_real_slates`：低于此值性能结论 NOT_EVALUATED
- `min_train_slates`、`min_test_slates`、`min_test_rows_per_role`：模型最低样本
- `test_fraction`：按完整日期划分的 holdout 比例
- `ridge_alpha`：确定性 ridge 正则
- promotion thresholds：MAE 改善、RMSE 最大退化、相关性最大下降
- `code_version`：建议填写 Git commit 加 working-tree 标识

## 3. 一次性 cycle

```bash
cd backend
python -m backtest.pipeline.cli run-cycle --config backtest/pipeline.local.json
```

返回 JSON。退出码 0 表示 cycle 编排完成，不等于模型通过。必须读取：

- `reports/latest-cycle-report.json`
- `catalog/registry.json`
- `models/promotion-report.json`
- `models/MODEL_CARD.md`
- backtest summary 和 failures

## 4. Registry 完整性复核

```bash
python -m backtest.pipeline.cli verify-registry --config backtest/pipeline.local.json
```

任何 missing 或 hash/size mismatch 返回 FAIL 和非零退出码。

## 5. 工资 CSV capture inbox

放置：

```text
inbox/
  DKSalaries.csv
  DKSalaries.csv.capture.json
  provider-metadata.json            # 可选原始 metadata
```

Sidecar 示例见 `backtest/salary-capture-sidecar.example.json`。Capture 必须发生在 first lock 之前。此路径只完成不可变工资池捕获，默认仍被 `provider_game_set_unverified`、feature 和 identity mapping 阻塞，不会自动宣称平台 Game Set 已验证。

## 6. 完整 feature upload inbox

推荐每个 slate 一个目录：

```text
inbox/dk-mlb-YYYY-MM-DD-main/
  dk-mlb-YYYY-MM-DD-main.features.json
  dk-mlb-YYYY-MM-DD-main.actuals.json     # 可选，缺失时尝试 StatsAPI builder
  provider-game-set-evidence.json         # 真实资格必需
  identity-mapping-audit.json             # 直接供应 actuals 时必需
  artifact-manifest.json                   # 直接供应 postgame raw 时必需
  provenance-manifest.json                # 可选补充
  raw/
    provider-slate.json
    salary-export.csv
    pregame-stats.json
```

要求：

- raw 文件 SHA-256 必须覆盖 features.sources[].raw_sha256。
- provider evidence 格式见 `backtest/provider-game-set-evidence.example.json`。
- evidence source URL、身份与 captured_at 会交叉核验，且 captured_at 必须早于 lock。
- 若直接供应 actuals，`artifact-manifest.json` 必须把 actuals.raw_stats_artifact_ids 对应到上传目录中的原始 postgame 文件、角色、URL 和时间。示例见 `backtest/artifact-manifest.example.json`。
- 若缺 actuals，feature 必须提供可用 game IDs 和 MLBAM IDs，StatsAPI builder 将生成全池 actuals、identity audit、raw game feeds 和 DNP evidence。
- 不支持也不尝试抓取 DraftKings 私有历史数据库。无法合法取得历史 pool 时，应从未来真实上传开始积累。

## 7. 在线补 actuals 与离线重放

在线：

```json
{"offline": false, "retries": 3, "timeout_seconds": 20.0}
```

网络失败记为 `RETRY_LATER`，下一次 cycle 可重试。成功 response bytes 写入 immutable cache。

离线：

```json
{"offline": true}
```

只允许命中缓存。缺少任何 game feed cache 时记为 `OFFLINE_BLOCKED`，不能回退到合成数据。

## 8. 独立 backtest

保留原有命令，并可附加 registry 与候选模型：

```bash
python -m backtest.cli \
  --site dk \
  --slate-dir /path/to/staged-qualified-slates \
  --output-dir /path/to/output \
  --seed 20260730 \
  --lineups-per-method 5 \
  --qualified-registry /path/to/catalog/registry.json \
  --candidate-model /path/to/models/candidate-model.json
```

`candidate_model` 只追加第四种方法。random、legacy、optimized 仍使用原 projection 和相同 lineup 数。

## 9. Cron/systemd/GitHub schedule 调用示例

以下仅是调用模板，本次交付未创建或修改任何任务。

Cron：

```cron
17 * * * * cd /srv/mlb-optimizer/backend && /srv/mlb-optimizer/backend/.venv/bin/python -m backtest.pipeline.cli run-cycle --config backtest/pipeline.prod-like.json >> /var/log/mlb-pipeline.log 2>&1
```

systemd ExecStart：

```ini
ExecStart=/srv/mlb-optimizer/backend/.venv/bin/python -m backtest.pipeline.cli run-cycle --config /srv/mlb-optimizer/backend/backtest/pipeline.prod-like.json
```

GitHub scheduled job command：

```yaml
- run: cd backend && uv run python -m backtest.pipeline.cli run-cycle --config backtest/pipeline.ci.json
```

同一 root 的并发调用会因 `.run-cycle.lock` 立即失败，调度器应记录失败而不是并发重试同一目录。

## 10. 模型审查

按以下顺序审查：

1. registry 只有真实 qualified/backtested slates 进入 dataset。
2. dataset manifest 的 slate hashes 与 registry qualification 对齐。
3. train dates 严格早于 holdout dates，同日不跨分割。
4. event_time_columns、chronological split、determinism 全部 PASS。
5. hitter/pitcher 各自达到最小 test rows。
6. MAE/RMSE/correlation/calibration gates 通过。
7. candidate lineup backtest 样本达到门槛。
8. 由独立负责人决定后续动作。本流水线不会自动启用模型。

## 11. 故障处理

- `hash_or_size_mismatch`：视为归档损坏或篡改，slate 进入 rejected。不要覆盖原文件，重新以新 slate/artifact 流程采集。
- `late capture`：不可补写历史 captured_at，必须 rejected。
- `uniform salary`：不能作为真实 DK Classic 验证样本。
- `provider_game_set_unverified`：补齐显式 provider evidence，不能手改布尔值。
- `missing/extra actuals`：重新运行 full-pool builder 或修复身份映射。
- `identity ambiguity`：人工或可信目录显式消歧后重新构建新工件。
- `OFFLINE_BLOCKED`：先在允许网络的受控环境填充对应 cache，再离线重放。
- `REJECTED_NOT_EVALUATED`：样本不足，不是模型失败，也不是提升证据。
