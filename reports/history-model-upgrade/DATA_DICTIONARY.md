# 数据字典

## 1. Registry 顶层

| 字段 | 类型 | 说明 |
|---|---|---|
| schema_version | string | 当前为 `1.0` |
| created_at | UTC timestamp | registry 首次创建时间 |
| updated_at | UTC timestamp | 仅语义变化时更新 |
| slates | object | key 为 slate_id，value 为 slate entry |

## 2. Slate entry

| 字段 | 类型 | 说明 |
|---|---|---|
| slate_id | string | 稳定唯一 slate 标识 |
| state | enum | captured / awaiting-results / qualified / rejected / backtested |
| data_kind | string | 只有 real 可通过资格门禁 |
| site | string | 当前严格资格路径要求 dk |
| captured_at | timestamp | 初始捕获时间 |
| effective_at | timestamp/null | 工件内容对应的有效时间或 snapshot 时间 |
| provider | string | direct_upload 或 draftkings_direct_upload 等 |
| provider_slate_id | string/null | 平台 slate 身份 |
| draft_group_id | string/null | DraftGroup 身份 |
| provider_game_set_verified | boolean | 只有显式证据验证后才为 true |
| provider_verification | object/null | verified_at 与 evidence_artifact_ids |
| artifacts | array | 不可变 artifact metadata |
| feature_file | path/null | 已归档 feature snapshot |
| actuals_file | path/null | 已归档 full-pool final actuals |
| provenance_manifest | path/null | 可选 provenance manifest |
| qualification | object/null | 每项检查、hash 和最终状态 |
| rejection_reasons | array | 去重排序的拒绝原因 |
| blockers | array | 尚未完成但可后续补齐的阻塞 |
| backtest | object/null | summary path/hash、seed、lineup 数 |
| state_history | array | from/to/at/reason 审计轨迹 |

## 3. Artifact metadata

| 字段 | 类型 | 说明 |
|---|---|---|
| artifact_id | string | slate 内稳定 ID |
| role | string | platform_salary_snapshot、raw_source_artifact、provider_game_set_evidence、postgame_mlb_stats 等 |
| path | absolute path | pipeline runtime 中只读归档路径 |
| source_url | string/null | 原始来源 URL，不允许后续变化 |
| captured_at | timestamp | 实际归档或证据声明时间 |
| effective_at | timestamp/null | 内容生效或对应 snapshot 时间 |
| byte_count | integer | 归档字节数 |
| sha256 | string | 小写 64 位 SHA-256 |
| immutable | boolean | 固定为 true |

## 4. provider-game-set-evidence.json

| 字段 | 必需 | 说明 |
|---|---|---|
| schema_version | 是 | `1.0` |
| provider | 是 | 例如 draftkings |
| provider_slate_id | 二选一 | 必须与 feature/registry 身份相交 |
| draft_group_id | 二选一 | 必须与 feature/registry 身份相交 |
| source_url | 是 | http(s) 来源，必须与 artifact metadata 相同 |
| captured_at | 是 | 带时区且早于 lock，必须与 artifact metadata 相同 |
| evidence_type | 建议 | 证据类型说明 |
| notes | 可选 | 人工审计备注 |


## 5. artifact-manifest.json

用于历史 direct upload 声明原始工件，尤其是 supplied actuals 所引用的 postgame feeds。顶层为 schema_version 1.0 与非空 artifacts 数组。每条记录包含 artifact_id、role、上传目录内相对 path、http(s) source_url、带时区 captured_at，以及可选 effective_at。路径不能逃出 upload 目录，固定系统 artifact ID 不能复用。示例见 `backend/backtest/artifact-manifest.example.json`。

## 6. Feature snapshot 关键字段

Feature schema 沿用 `backtest.contracts.SlateFeatureSnapshot`。本 pipeline 重点使用：

- `data_kind`, `slate_id`, `site`, `contest_style`
- `provider_slate_id`, `provider_game_set_verified`
- `slate_start`, `lock_time`, `snapshot_as_of`
- `game_ids`, `games[].scheduled_start`
- `sources[].source_url/raw_sha256/available_at/retrieved_at`
- `players[].mlbam_id/game_id/position/salary/projected_points/feature_values`
- `settings`，保留工资帽、人数、位置、锁定、排除、最低工资、stack count 等优化器约束

## 7. Actuals 关键字段

Actuals schema 沿用 `backtest.contracts.SlateActualPoints`。资格路径要求：

- data_kind 与 feature 相同且为 real
- coverage_scope 为 `all_feature_players`
- points IDs 与 feature player IDs 精确相等
- source_final 为 true
- raw_stats_artifact_ids 全部在 registry 中
- DNP record 的 actual_points 为 0 且有 evidence
- coverage_summary 的 missing_ids 与 extra_ids 均为空

## 8. Training dataset

标识列：

- slate_id, slate_sha256, site
- slate_start, slate_date, game_start, feature_available_at
- mlbam_id, role

对照与目标：

- legacy_projection，仅用于比较
- target_actual_points，模型 target

基础特征：

- salary
- batting_order
- is_confirmed, is_expected, is_unconfirmed
- position_p, position_c, position_1b, position_2b, position_3b, position_ss, position_of

自定义特征：

- 来自 player.feature_values
- 规范化为 `fv_<name>`
- 只接受 bool/int/float
- 禁止未来字段、AvgPointsPerGame 和 available_at 后缀字段

## 9. Candidate model artifact

| 字段 | 说明 |
|---|---|
| artifact_type | candidate_projection_model |
| status | CANDIDATE_ONLY_NOT_DEPLOYED |
| algorithm | deterministic_standardized_ridge |
| separate_roles | true |
| feature_schema | 训练和推理固定顺序 |
| ridge_alpha | 正则参数 |
| seed | 审计 seed |
| code_version | 调用配置中的代码版本 |
| dataset_sha256 | 训练 CSV hash |
| data_slate_hashes | 每个 slate 的 feature/actuals hash |
| training_cutoff_date | 训练集最后日期 |
| holdout_start_date/end_date | 完全留出测试日期范围 |
| role_models | hitter/pitcher 的均值、尺度、截距、系数与训练样本信息 |

## 10. Promotion report

关键字段：status、production_action、production_default_replaced、reason、split、minimums、training_shortfalls、leakage_checks、determinism、fixed_completely_held_out_test_metrics、role_gates、walk_forward_validation_on_pre_holdout_dates、thresholds 和 limitations。
