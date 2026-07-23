# MLB Optimizer 数据缺口 TODO

> 产品定位：当前 Optimizer 只提供分析与候选阵容研究，不承诺生成可直接上传至 DraftKings/FanDuel 的文件。优先级以“是否影响分析结果精度”为准。

## 缺失数据、影响与严重程度

| 数据缺口 | 对当前分析功能的影响 | 严重程度 | 后续处理 |
|---|---|---:|---|
| 当日确认首发、临场撤下与伤病状态 | 可能把不出场或临时缺阵球员列为高价值选择，直接污染排序和阵容分析 | 严重 | 建立 MLB StatsAPI 主源、DFF 补充、RotoWire 交叉校验；记录状态时间与冲突 |
| 准确打序及打序确认时间 | 打序乘数最高可造成约 15% 调整；预计打序若被当作确认打序会明显影响打者排序 | 严重 | 区分 expected/confirmed；按球队保存确认时间；锁盘前高频校验 |
| 目标 Slate 的完整比赛和球员范围 | 混入非目标比赛或遗漏目标球员会改变可选池、堆叠和最优组合 | 严重 | 数据模型增加平台、Slate ID、比赛集合和锁定时间；按 Slate 隔离缓存 |
| 先发投手确认、投球限制与近期用量 | 错误先发或受限投手会严重高估局数、三振和胜投概率 | 严重 | 加入近 3–5 场投球数/局数、伤愈复出及预计投球限制 |
| 对手打线质量与球队三振率 | 当前投手对手修正主要依赖 Vegas 隐含得分，无法准确反映对手 K%、左右打结构 | 高 | 增加球队对左右投手 K%、wOBA、ISO、BB% 和预计打线聚合 |
| 打者真实左右投手拆分覆盖率 | 缺失时使用赛季总体数据，可能误判强/弱侧 platoon | 高 | 监控真实拆分覆盖率、样本量和更新时间；小样本回归联盟均值 |
| 伤病严重程度和预计复出信息 | 简单状态码不能区分休息、每日观察、IL、伤愈复出与上场限制 | 高 | 标准化 availability、injury_type、reported_at、expected_return |
| 天气临场变化和延赛风险 | 降雨、风向和温度变化会影响比赛是否进行及打者/投手环境 | 高 | 按球场和开赛时间刷新；增加延迟/延期概率及屋顶状态 |
| 球场、裁判与屋顶状态 | 影响得分环境、三振/保送和比赛条件，目前裁判与屋顶缺失 | 中 | 球场因子保留；研究可靠的主审与屋顶状态来源 |
| Bullpen 质量和可用性 | 影响打者后半场对位、先发胜投及被换下后的得分环境 | 中 | 增加近 3 日牛棚用量、赛季 FIP/K% 和高杠杆投手可用性 |
| DK/FD 官方薪资与平台位置 | DFF 与平台当日定义若不一致，会影响价值比较和位置稀缺性分析 | 高 | 官方 CSV 作为权威源，DFF 作为补充；逐字段报告差异 |
| DK/FD 官方球员外部 ID | 不影响预计分计算和站内分析，但影响未来平台 CSV 上传 | 低（当前定位） | 保留官方 CSV 导入能力；在启用上传功能前设为发布阻塞项 |
| DK/FD 官方比赛/Contest ID | 当前不负责上传时影响较小，但会影响精确区分多个同日 Slate | 中 | 与 Slate 模型一并补充，不能使用 DFF 内部 ID 冒充 |
| 数据刷新与历史版本 | 无法证明分析使用的是锁盘前最新状态，也难以回测来源变化 | 高 | 保存 source_updated_at、fetched_at、版本摘要和差异日志 |

## 推荐实施顺序

1. 当日确认首发、伤病和临场撤下。
2. 准确打序及 expected/confirmed 状态。
3. 先发投手确认、近期用量和投球限制。
4. 投手对手打线 K%/wOBA/ISO/左右打结构。
5. 目标 Slate 的比赛与球员范围隔离。
6. 真实左右投手拆分覆盖率与小样本回归。
7. 天气、延赛和屋顶状态。
8. Bullpen、裁判等二级环境数据。
9. DK/FD 官方 ID 与上传相关字段（启用上传功能前完成）。

## 数据质量门禁（待实现）

- 每名参与排序的球员必须有球队、对手、位置、薪资、预计分和数据更新时间。
- `confirmed` 只能由明确确认来源产生，预计打序不得升级为确认。
- 已确认不出场、IL 或比赛延期的球员不得进入默认候选池。
- 每次刷新报告球员新增、删除、打序变化、状态变化和来源冲突数量。
- 数据超过刷新 SLA 时标记为 stale，不能显示为“最新分析”。
- 任何来源冲突保留主源结果，同时向分析结果输出明确 warning。

## 当前研究

- [x] 完成“当日确认首发、伤病和临场撤下”现状研究（2026-07-23）。
- [x] 实现“预计候选池 → 官方确认打线 → 临场撤下”的状态迁移（2026-07-23）。

### 2026-07-23 研究结论

实测时间：2026-07-23 11:34（Asia/Shanghai），距离当天首场比赛约 4 小时 40 分钟。

| 检查 | 结果 | 风险 |
|---|---:|---|
| MLB 当天比赛 | 5 场 | 正常 |
| MLB StatsAPI 已发布打序 | 0 支球队 | 官方打线发布前无法由 boxscore 建立打者池 |
| 当前实时分析池 | 10 人 | 只包含预计先发投手 |
| 当前实时分析池打者 | 0 人 | 严重：赛前打者分析不可用 |
| 当前实时分析池投手 | 10 人 | 其中只有 6 人匹配 DFF 当前 DK Slate 薪资 |
| DFF 当前 DK 完整候选池 | 95 人 | 已成功抓取，但目前不会创建缺失打者，只给已有球员补字段 |
| DFF 打序覆盖 | 0/95 | 当前时点尚无预计打序 |
| DFF 伤病标记 | 1/95 为 DTD | 覆盖很稀疏，不能单独作为完整伤病主源 |
| DFF 状态 | 6 expected、89 unconfirmed | expected 主要是预计先发投手 |

根因：

1. `lineup_data._get_live_player_pool()` 只从 MLB boxscore 的 `battingOrder` 创建打者。
2. 官方打线尚未发布时，`battingOrder` 为空，因此不会创建任何打者。
3. `apply_salary_slates()` 只给已经存在的 Player 合并 DFF 数据，不会从 DFF 完整候选池创建 Player。
4. DFF 的 `injury_status` 已被解析，但 Player 模型没有对应字段，合并时也没有使用该字段。

建议的数据状态模型：

1. **预计候选池**：DFF 完整 Slate 创建全部球员；状态为 `unconfirmed`，有预计打序时为 `expected`。
2. **官方确认打线**：MLB StatsAPI `battingOrder` 发布后，以 MLBAM ID/姓名+球队匹配并覆盖打序，状态升级为 `confirmed`。
3. **交叉校验**：RotoWire 只验证确认/预计状态、打序及 DK 薪资，不作为完整候选池主源。
4. **临场撤下**：球员从已确认打线消失、进入 IL/非激活状态或来源明确标记 OUT 时，设置为 `dnp`，默认排除。
5. **来源时间**：分别记录 `source_updated_at`、`fetched_at`、`lineup_confirmed_at`，禁止把旧状态显示成最新状态。

实现验收标准：

- 官方打线发布前，分析池必须包含目标 Slate 全部 DFF 候选球员，而不是 0 名打者。
- 官方打线发布后，每支球队应有且仅有 9 名 `confirmed` 打者。
- `expected` 不得在没有官方信号时升级为 `confirmed`。
- OUT/IL/DNP 球员默认不参与推荐，但仍保留在数据中供审计。
- 每次刷新输出新增、删除、打序变化、状态变化和来源冲突计数。

### DFF / RotoWire 网页端能力核查

核查时间：2026-07-23（Asia/Shanghai）。

| 能力 | Daily Fantasy Fuel 网页端 | RotoWire 网页端 | 采用建议 |
|---|---|---|---|
| 预计先发投手 | 显示 `PROJECTED`，今天 5 场共 10 名 | Daily Lineups 显示预计投手 | MLB StatsAPI 主源，DFF/RotoWire 校验 |
| 预计打者阵容 | DFF Starting Lineups 当前全部 `Lineup Pending` | 明日页面已有 10 支球队、90 名打者，状态为 `Expected Lineup` | RotoWire 适合补充预计打线 |
| 确认打者阵容 | 页面说明发布后显示 confirmed batting orders；Optimizer 有确认徽标 | 当日页面实测 34 支球队为 `Confirmed Lineup`、306 名打者 | MLB StatsAPI 主源，RotoWire 强校验 |
| 打序 | 确认发布前为空，发布后网页展示 | Expected/Confirmed 页面均按 1–9 顺序展示 | 保存 expected/confirmed 两种状态 |
| DTD/简单伤病标签 | Optimizer 实测 Jonatan Clase 明确显示 `DTD` | Daily Lineups 本身不在普通球员行显示伤病详情 | DFF 可作 DTD 补充 |
| 完整伤病报告 | MLB 导航未提供独立完整伤病表 | 独立 Injury Report 显示 Player、Team、Pos、Injury、Status、Est. Return | RotoWire 可作每日伤病校验，但返回日期部分为订阅内容 |
| IL/OUT 状态 | 当前 DFF Slate 未观察到样本，接口支持简单 `injury_status` | 公开表可见 7/10/15/60-Day IL、Out、Suspension 等状态 | 优先使用可核验状态；不依赖订阅字段 |
| 临场撤下事件 | 未显示公开的变更历史，只会更新当前阵容 | 未显示公开的撤下历史；当前阵容会变化，并提供 Lineup Alerts 入口 | 必须由项目保存快照并做差异检测 |
| 更新时间/变更时间 | 页面提供投影更新时间，但单个打线/伤病事件时间不足 | Injury Report 标注每日日期，单条精确事件时间不完整 | 项目自行记录 `fetched_at` 和首次观察时间 |

结论：

- **确认打线**：MLB StatsAPI 应作为权威源；RotoWire 网页适合作强校验，DFF 作次级校验。
- **预计打线**：RotoWire 网页当前明显早于 DFF，适合作为赛前分析补充源。
- **伤病状态**：DFF 可补 DTD；RotoWire Injury Report 覆盖 IL/Out/伤病类型更完整。
- **临场撤下**：两站公开网页都没有足够的事件历史，必须对每次阵容快照进行 diff；从 `confirmed` 阵容消失时标记为待复核，不能仅凭一次消失立即判定 DNP。

### 其他数据缺口的网页来源

核查时间：2026-07-23（Asia/Shanghai）。原则：优先接入公开页面明确展示的事实字段，保存抓取时间；不绕过登录、付费墙或访问限制。

| 数据缺口 | 可用网页与公开字段 | 项目采用方式 | 当前状态 |
|---|---|---|---|
| 近期状态与投影交叉检查 | DFF Projections：L5、L10、赛季 FP 均值、当前投影、Value | 合并进 DFF Slate 缓存；作为现有 MLB 近期数据和项目投影的补充/校验，不直接替换模型投影 | 已接入；实测 DK 95/95、FD 102/102 合并 |
| Vegas 比赛环境 | DFF Projections/Matchup Analysis：O/U、球队隐含得分、让分、胜率、近 5/10 场球队得分及失分 | 球员级 O/U、球队隐含得分和让分进入 Slate 缓存；The Odds API 仍为已配置时的主源 | 球员级字段已接入；比赛页历史待接入 |
| 天气、延迟与延期风险 | RotoWire Weather：温度、降水概率、风速/风向、Delay/Rainout 风险、逐小时预报 | `api.weather.gov` 继续作为主源；RotoWire 只产生聚合校验结果和冲突 warning，不保存原始表 | 待实现校验 |
| Bullpen 可用性 | RotoWire Bullpen Usage：逐日投球数、Last 3、Last 5 | MLB 比赛日志计算为主；RotoWire 只校验异常和覆盖率 | 待实现主源计算 |
| 主审裁判环境 | RotoWire Today's Umpire Stats：Ump、R/9、K/9、BB/9、AVG/OBP/SLG/OPS | 仅作为二级环境校验；主审未公布时保持缺失，不推断 | 待实现 |
| 左右投手拆分 | RotoWire Player Splits：vs L/vs R 的 AVG、OBP、SLG、OPS、ISO、wOBA、wRC+、K%、BB% | 项目持久化数据仍使用可合法复用的 MLB/pybaseball/FanGraphs 派生数据；RotoWire 只校验聚合差异 | 主源已有部分，覆盖率门禁待实现 |
| 预计打序趋势 | RotoWire Batting Order Changes：对 RHP/LHP 打序、近 5 场与此前对比、上场时间增减 | 只用于 expected lineup 先验和冲突告警；不能升级为 confirmed | 待实现 |
| 伤病严重程度 | DFF 行级 DTD；RotoWire Injury Report 的伤病类型、IL/Out/Suspension、预计复出（部分订阅） | DFF 公开 DTD 合并进球员缓存；RotoWire 只校验公开状态，不读取订阅字段 | DFF 字段和强不可用状态排除规则已接入；完整覆盖仍缺失 |
| 屋顶状态 | DFF 未发现稳定字段；RotoWire Daily Lineups/Weather 可显示 `Dome`，但不能区分可伸缩屋顶当日实际开闭 | MLB/球场官方信息继续作为待研究主源；RotoWire 只做内存校验 | 实际开闭状态缺失 |

使用边界：

1. DFF 公开球员行数据可作为项目补充数据，但所有记录必须携带 `source_url`、`last_updated`，并接受 MLB/官方 Slate 校验。
2. RotoWire 公开 Daily Lineups 的标准化快照按比赛日保存于 VPS，仅供内部校验和审计；不保存网页 HTML、不读取订阅字段，也不向用户重新分发其原始表。
3. 网页字段没有明确更新时间时，只记录项目的 `fetched_at`，不得把抓取时间冒充来源更新时间。
4. 付费字段（例如 DFF ownership、RotoWire 部分预计复出日期）不绕过权限获取。

### 2026-07-23 状态迁移实施结果

| 验收项 | 实测结果 |
|---|---:|
| MLB 当天比赛 | 5 场 |
| 官方打序尚未发布时的统一候选池 | 164 人 |
| 打者 | 154 人（此前为 0） |
| 投手 | 10 人 |
| DK 有薪资球员 | 95 人 |
| FD 有薪资球员 | 102 人 |
| 当前状态 | 153 `unconfirmed`、10 `expected`、1 `dnp` |
| 本次新增 | 164 |
| 警告 | 0 |

已实施规则：

1. DFF DK/FD 完整 Slate 的并集用于创建赛前候选池；尚无 MLBAM ID 时使用稳定的负数内部临时 ID。
2. DFF 的 `confirmed` 不会直接进入项目的 `confirmed`；第三方状态最高只可升级为 `expected`。
3. MLB StatsAPI 官方 `battingOrder` 是唯一可把打者升级为 `confirmed` 的主源。
4. `OUT`、`IL`、`INACTIVE`、`SUSPENDED` 等强不可用状态将球员标记为 `dnp`；`DTD` 只保留风险标记，不自动排除。
5. 如果同一球队已有更新的官方确认阵容，而此前确认球员被遗漏，则保留该球员用于审计并标记为 `dnp`。
6. 每次刷新输出新增、删除、打序变化和状态变化数量。
7. MLB 当前及上一赛季官方球员目录用于解析 MLBAM ID；实测 163/164 命中。唯一未匹配的 DFF 球员 Jose Miranda 已不在 MLB 体系，保留记录但标记 `dnp`。

仍需补强：

- 将刷新快照和状态变化持久化，保证服务重启后仍能识别临场撤下。
- 将 MLBAM 身份解析命中率加入健康检查；当前实测为 163/164（99.4%）。
- 在界面中明确展示 `unconfirmed`、`expected`、`confirmed`、`dnp` 和伤病标签。

### 2026-07-23 投手近期用量实施结果

数据来自 MLB StatsAPI 公开球员 `gameLog` 页面数据，不从低可信第三方推断确定的“限投数”。

已接入字段：

- 最近 5 次先发的比赛日期、比赛 ID、投球数、局数、三振和自责分。
- 上次先发日期、完整休息天数、上场投球数。
- 最近 3 次平均投球数和平均局数。
- `low`、`medium`、`high`、`unknown` 工作量风险及保守投影系数。

实测当天 10 名预计先发均取得近期比赛日志：

| 结果 | 数量 |
|---|---:|
| 日志覆盖 | 10/10 |
| 正常休息/低风险 | 9 |
| 中等风险 | 1 |
| 高风险 | 0 |
| 未知 | 0 |

中等风险样本为 Griffin Canning：最近一场 65 球，近 3 场平均 71.3 球、4.22 局。项目只标记“近期工作量偏低”，投影系数设为 0.92；没有公开明确证据时不会显示成“球队确认限投”。

同时修复：

1. 原打者近 15 天日志调用向当前 `statsapi` 包传入不支持的 `startDate/endDate` 参数，异常被回退逻辑吞掉，导致缓存长期显示 0 场。
2. 现改用 MLB 官方 `person` 页面 `gameLog` 数据，并增加缓存版本；旧的错误零值缓存会自动失效。
3. 实测 Shohei Ohtani 近 15 天正确取得 10 场记录，不再是 0 场。
4. 每日球员池快照已经持久化到 `player_pool_snapshots/<date>`；服务重启后会加载上一快照继续检测临场撤下和状态变化。

### 2026-07-23 第一阶段 P0 实施方案研究

范围：线上刷新、Slate 隔离、对手打线质量、投球限制、完整伤病、数据新鲜度门禁。

#### 开源方案取舍

| 能力 | 可复用开源方案 | 决策 |
|---|---|---|
| 棒球比赛、官方打线和 probable pitcher | `toddrob99/MLB-StatsAPI` / MLB StatsAPI | 继续作为比赛、gamePk、官方打线和 probable pitcher 主源 |
| 球员/球队高级统计和左右拆分 | `pybaseball`（Baseball Savant、FanGraphs、Baseball Reference） | 继续复用现有依赖，在后台缓存路径计算；不在请求路径做大批量抓取 |
| 定时任务 | APScheduler | 保留现有稳定版本，但从 FastAPI 多 worker 生命周期移出，改为单独 refresh worker |
| 单机防重入 | OS 文件锁（`fcntl`）或开源 `filelock` | 当前单 VPS/共享持久盘优先使用文件锁，避免引入 Redis |
| 多实例任务队列 | RQ + Redis/Valkey | 暂不引入；只有扩展到多主机/多实例后再采用 |
| 数据结构校验 | 现有 Pydantic；可选 Pandera | 第一阶段使用 Pydantic 加自定义完整性门禁，当前数据不是 DataFrame 主流程，无需新增 Pandera |
| 健康指标 | Prometheus Python client | 第一阶段先扩展 `/health` 和持久化 refresh status；需要外部告警时再暴露 Prometheus 指标 |

结论：没有可信开源项目能够提供完整、可保证的 DK/FD 官方 Slate、临场伤病或球队确认 pitch limit。开源组件用于采集、计算、调度和质量控制；事实数据仍需 MLB、平台 CSV、DFF 和受使用条款约束的 RotoWire 分层组合。

#### DFF / RotoWire 实测覆盖

实测日期：2026-07-23。

| P0 数据 | DFF | RotoWire | 采用方式 |
|---|---|---|---|
| 多 Slate 列表 | 公开页面调用 `/data/slates/next/mlb/{site}`；当天 DK 5 个、FD 6 个，含 Classic/Main/Night/All Day/Showdown、开始时间、比赛数和 DFF slate token | Daily Lineups 当天列出 DK Classic 2 个、Showdown 3 个、Tiers 1 个，并提供 RotoWire slateID | DFF 用于建立可分析的 Slate 列表；RotoWire 只校验名称、比赛数和开始时间；两者 ID 均不得冒充官方 Contest ID |
| Slate 球员范围 | `/data/playerdetails/mlb/{site}/{token}` 返回完整球员、薪资、位置、球队、对手 | 按所选 Slate 展示阵容与 DK 薪资 | DFF 作为自动候选池；官方 CSV 上传后覆盖薪资、位置和官方 ID |
| 预计/确认打线 | `starter_flag`、`probable_flag`、`depth_rank`、手性 | Expected/Confirmed、1–9 打序、打者手性 | MLB 官方打线是 confirmed 唯一主源；DFF/RotoWire 只补 expected 和产生冲突警告 |
| 先发投手角色 | `probable_flag`、`days_rest`、`starter_flag` | 预计投手、手性、ERA，并定义 `PRIM` 为非先发但预计投多局的 primary pitcher | MLB probable 主源；RotoWire 的 `PRIM` 只做角色风险校验 |
| 明确 pitch limit | 未发现结构化限制字段 | 公开 Daily Lineups 未发现结构化限制字段 | 保持“推断工作量风险”和“明确球队限制”两个字段分离；没有可靠来源时不得声称已确认限投 |
| 伤病 | JSON 有 `injury_status`、`inj_det`，但当天抽查 DK Night 39 人、FD All Day 108 人均为 0 条非空伤病 | Injury Report 页面存在，但完整表要求订阅 | DFF 只能作为稀疏补充；MLB roster/transactions/IL 为主源，RotoWire 不绕过订阅 |
| 对手打线质量 | 有对手、手性、打序、`opp_rank`，但没有透明的 K%/wOBA/ISO/BB% 明细 | Daily Lineups 有预计打线与手性；另有 splits 页面但受使用条款限制 | 用 MLB/pybaseball 持久化统计计算 lineup-weighted 聚合；DFF/RotoWire 只校验阵容组成 |
| 来源更新时间 | 页面给出 Projections Last Updated | Daily Lineups 显示目标日期，但没有可靠的单条变更时间 | 保存 `source_updated_at`（只有来源明确提供时）、`fetched_at`、哈希与首次观察时间 |

#### 确定的实施顺序

1. 将调度器移出 API worker：新增独立 refresh worker、非阻塞文件锁、原子缓存写入、每来源成功/失败/耗时/连续失败状态。
2. 新增 `Slate` 模型：`site`、内部 `slate_key`、`provider_slate_id`、名称、类型、比赛集合、开始/锁定时间、来源和抓取时间；缓存路径改为 `date/site/slate_key`。
3. 接入 DFF 多 Slate 列表和逐 Slate 球员数据；默认只自动选择 Classic/Main，不把 Showdown/Tiers 混入 Classic optimizer。
4. MLB schedule/gamePk 与 Slate 比赛集合进行匹配；RotoWire 标准化公开阵容按比赛日持久化，用于校验 Slate 数量、开始时间、预计打线和投手角色。
5. 基于 expected/confirmed 1–9 打线聚合 vs 投手手性的 PA、K%、BB%、wOBA、ISO；记录覆盖率与样本量，低样本回归联盟均值。
6. 伤病接入 MLB roster/transactions/IL 状态；DFF 的 `injury_status`/`inj_det` 作为补充。结构化区分 `availability`、`injury_type`、`reported_at`、`expected_return` 和 `restriction_note`。
7. 加入质量门禁：Slate 比赛集合一致、每队候选覆盖、确认打线每队 9 人、身份解析率、薪资/位置覆盖率、来源新鲜度和冲突计数。严重门禁失败时返回 `partial/stale`，不显示“最新分析”。

#### 第一阶段验收线

- API 多 worker 不再重复启动抓取任务，同一刷新任务不能并发执行。
- DK/FD 每个 Classic Slate 可独立选择、缓存和优化；跨 Slate 球员为 0。
- 锁盘前 DFF/MLB 刷新间隔不超过 10 分钟，90 分钟内目标为 2–5 分钟；任何来源失败保留最后成功快照并明确标记 stale。
- 每名投手都有对手预计/确认打线的聚合质量指标、覆盖率和样本说明。
- 明确 OUT/IL/DNP 默认排除；DTD 和推断投球限制只降级或警告，不伪装成确认状态。
- `/health` 能分别报告 DFF DK/FD、MLB、RotoWire 校验和统计缓存的最后成功、数据年龄、行数、耗时与连续失败次数。

#### 2026-07-23 第一阶段实施进度

已完成：

1. 独立 `data_worker.py`、非阻塞文件锁、原子 JSON 替换和每来源刷新状态；VPS systemd 服务与 API scheduler drop-in 已加入部署流程。
2. DFF DK/FD 多 Slate 发现、日期/站点/Slate 隔离缓存、默认 Classic 选择和逐 Slate 球员加载。
3. `/players/slates` 与带 `site + slate_id` 的 `/players/today`；旧的默认 `/players/today` 保持兼容。
4. 前端只展示 Classic Slate，禁止把 Showdown/Tiers 送入 Classic optimizer；切换站点或 Slate 时清除旧锁定、排除和 CSV 覆盖。
5. DFF 球队集合与 MLB `gamePk` 匹配后回写 Slate；统一 `SD/TB` 为 `SDP/TBR`，避免拆成重复球队。
6. `/health` 已显示 worker 开关、运行中状态、DFF/MLB/天气/赔率/球员池/RotoWire 校验的最近结果。

当日真实数据验收：

| 检查 | 结果 |
|---|---:|
| DFF DK Slate | 5 个（2 Classic、3 Showdown） |
| 默认 DK Classic | 3 场、69 人 |
| 默认 DK Classic 有效薪资 | 69/69 |
| Night DK Classic | 2 场、39 人 |
| 页面 DK 默认/Night 切换 | 通过 |
| 页面 FD Classic 加载 | 通过 |
| 后端测试 | 51/51 通过 |
| 前端生产构建 | 通过 |

#### 2026-07-23 Slate 加载性能改造

已将用户请求路径改为“后台更新、前台读快照”：

1. Worker 每轮预取 DK/FD 所有 Classic Slate 的完整 DFF 球员数据。
2. 当日赛程已知后每 10 分钟刷新；首场比赛前 90 分钟内每 2 分钟刷新。
3. `/players/slates` 有缓存时不再同步请求 DFF。
4. 按 Slate 的 `/players/today` 优先读取持久化综合球员池快照，不再重复执行 MLB schedule、boxscore、球员日志、天气等网络扇出。
5. 快照和薪资超过新鲜度目标时继续快速返回最后成功数据，但标记 `partial` 并显示后台刷新提示。
6. 只有冷启动且完全没有缓存时才允许同步构建一次数据。

本地真实接口计时：

| 请求 | 改造前 | 改造后 |
|---|---:|---:|
| DK 默认 3 场 Slate 球员池 | 约 35–50 秒 | 0.034 秒 |
| DK Night 2 场 Slate 球员池 | 约 35–50 秒 | 0.022 秒 |
| DK Slate 列表 | 需要网络时为秒级 | 0.002 秒 |

后端自动测试增加到 52 项，全部通过。

#### 2026-07-23 VPS 存储与首页调整

1. 数据继续以 `/var/lib/diamscore/cache` 作为线上持久化目录，不启用 Cloudflare D1。
2. RotoWire 公开 Daily Lineups 按比赛日保存标准化快照；同一天刷新覆盖当天版本。
3. 首份实测快照为 90 人、17.7 KB，匹配项目球员 80 人。
4. 首页营销 Hero、Launch optimizer、Compare scoring、Slate readiness 和统计卡片已经删除，首屏直接显示 Optimizer。
5. 数据状态提示位于 DK/FD Slate 下方，并可通过右侧关闭按钮隐藏。

下一批：

1. 对手预计/确认打线的 K%、BB%、wOBA、ISO 聚合、覆盖率和小样本回归。
2. MLB roster/transactions/IL 结构化伤病与 availability。
3. 新鲜度、身份解析率、每队候选数、确认打线 9 人等质量门禁及 stale 状态。
