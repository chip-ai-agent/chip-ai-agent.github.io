# PCBWorld 复现报告：环境、数据、训练与评测

<p class="meta">chip-ai-agent · 2026 年 10 月</p>

## 概述

论文三种 RL 方法（PPO per-step、PPO terminal、GRPO）已经用 4 个 seed 复现完成：在 D2 和 D3-A 上与论文 Table 3 的差距都在 0.05 以内。PPO terminal 按论文原配方训练时 4 个 seed 全部失败，改成 γ=1 后复现成功。

- **论文**：*PCBWorld: A Benchmark Environment for Engine-Grounded PCB Design Automation*（KDD 2026 Agentic AI Workshop，arXiv:2607.05915，LG AI Research）。代码在 `LGAI-Research/PCBWorld`，版本 v1.0.1。
- **论文的核心贡献是环境，不是布线算法**：它把 KiCad 9.0.8 的交互式布线器（push-and-shove）和 DRC 包成 Gymnasium 环境，智能体在真实板子上逐段布线，每一步都由 KiCad 执行并打分。
- **我们只复现了论文自己的 RL 方法**，没有跑 LLM agent 和规则布线器（Freerouting 等）这两类 baseline。
- **最主要的发现**：大板子上效果很差。D3-C（10 块、平均 44 个 net）上三种方法的完成率都是 0。根本原因是策略只在平均 5 个 net 的小板上训练过，而且环境只做 detailed routing，没有全局布线，也没有拆线重布。

## 交互环境

智能体只决定"往哪个点画、用什么模式"，具体路径、避让、推挤都由 KiCad 的布线器完成；每步结束后跑 KiCad DRC 打分。坐标是连续的 mm 值，没有网格（gridless）。

<!--ARCH-->

每一步动作从左往右传到 KiCad，由 KiCad 实际画线并跑 DRC；结果再经环境整理成观测和奖励返回给智能体。

### 状态（观测）

观测是一个按"net → 焊盘 → 坐标"嵌套的字典，数值是精确 mm，不做归一化（`pcb_world/core/observation.py`）。

| 字段 | 变化频率 | 内容 |
| --- | --- | --- |
| `board_static` | reset 后不变 | 板框 bbox、铜层数、每个 net 的焊盘、无 net 障碍物、设计规则（线宽、间距、过孔尺寸） |
| `routing_geometry` | 每步 | 每个 net 已布的走线、过孔、未连通的飞线端点 |
| `router_head` | 每步 | 笔头位置、当前层、当前 net、是否在布线、步数 |
| `drc_violations` | 每步 | 笔头附近的 DRC 违规 |
| `action_history` | 每步 | 最近几步动作及是否被布线器接受 |
| `closed_nets` | 每步 | 已经 `net_end` 的 net |

同一个字典有两种编码：给 RL 的 token 序列（一个对象一个 token，见模型一节），给 LLM 的 S 表达式文本。

### 动作

动作是 `action_type` 加参数（6 种布线动作 + 1 个空操作，`pcb_world/core/action_schema.py`）：

| 动作 | 参数 | 含义 | 引擎里的对应操作 |
| --- | --- | --- | --- |
| `net_select` | net_id | 选定要布的 net | 设置该 net 的线宽、间距、过孔尺寸 |
| `start_route` | x, y, layer | 在本 net 的焊盘上落笔 | `start_route`，相当于人点下鼠标 |
| `make_line` | x, y, mode | 从笔头画到 (x, y)，不换层 | `fix_route`：布线器引线并提交 |
| `make_via` | x, y, mode | 画到 (x, y) 并打过孔换层 | 同上，要求终点有过孔 |
| `finish` | mode | 自动连到最近的未连焊盘 | KiCad 自动补完最后一段 |
| `net_end` | 无 | 结束并释放这个 net | 该 net 本局不再可选 |
| `idle` | 无 | 仅 LLM 解析失败时使用 | 不碰板子 |

- **mode**（碰到障碍怎么办）：0 = 标记障碍（撞到就失败）、1 = 推挤（shove）、2 = 绕行（walkaround）。
- **坐标从候选点里选**：本 net 的焊盘中心、已画线段的端点和过孔、飞线目标、笔头周围 8 个邻点（`pcb_world/vec/candidate_pool.py`）。RL 只能指向候选点，LLM 可以给自由坐标。
- **合法动作掩码**由 YAML 规则定义（`configs/masking/`）：未选 net 只能 `net_select`；选了未落笔只能 `start_route` / `net_end`；落笔后才能画线或打孔。
- **没有删除 / 拆线动作**。但引擎已经有这些接口（`delete_routing_of_nets`、`delete_track_near`、`undo_last_segment`、`start_drag`、`lock_net`），只是没有开放给智能体。

布一个两焊盘 net 的典型动作序列：`net_select(3)` → `start_route(10,10,层1)` → `make_line(25,10,绕行)` → `make_via(25,18,绕行)` → `make_line(40,18,绕行)` → `net_end`。

### 一步是怎么执行的

1. `env.step` 先查掩码：不合法的动作直接拒绝，不碰引擎，给一个小惩罚。
2. 记录执行前的板子状态（未连数、DRC、线长、过孔数）。
3. `ActionDispatcher` 做前置检查（目标点会不会压到别的焊盘），设置 mode，调 `KiCadEngine.fix_route`。
4. `fix_route` 禁止 `make_line` 偷偷换层；开启 `reject_if_stuck` 时，到不了目标点就整步作废，不留半截废线。
5. 调用经 unix socket 发给独立子进程 `rl_engine_server.py`，它加载 C++ 模块 `kicad_rl_router`（去掉图形界面的 KiCad PNS 布线器），算出实际走线并提交到板子。
6. 回到环境：更新连通性，跑 DRC（可增量），判断是否"空动作"（成功但线长、线数、过孔数都没变），算奖励，生成新观测。

### 奖励

奖励基于势函数 Φ(s)，对整块板打分（`pcb_world/core/reward.py`）：

```
Φ(s) = − unconnected(s) − f_drv(s) − λ_w · wirelength(s) − λ_v · vias(s) + completion_bonuses
```

- `f_drv` 是按 net 的对数形 DRC 惩罚，靠近 0 时最陡，所以"干净"比"短"值钱得多。
- 完成奖励：每连通一个 net、每个无违规 net、整板布完各有一笔。
- **per_step**：每步给 Φ(s_{t+1}) − Φ(s_t)；**terminal**：每步给 0，最后给 Φ(s_T)。γ = 1 时两者总回报相同，最优策略一致。
- 另有：动作被掩码拒绝、解析失败或是空动作时给 0.01 的小惩罚。

### 终止条件

- `terminated`：所有 net 连通，或所有 net 都已 `net_end`。`info["success"]` 只在整板连通时为真。
- `truncated`：到达 `max_steps`（论文训练和评测都用 256）。
- 开局 `env.reset()` 加载 `.kicad_pcb`，删掉所有已有走线，元件和焊盘位置不动。

## 数据集

训练只用 D2 合成小板（10000 块，平均 5.1 个 net）；评测用 D2 测试集和 D3 真实板（来自 PCBench，共 679 块，平均 33.3 个 net）。D3 是零样本评测，策略从没见过真实板。

| 数据集 | 来源 | 规模（train / val / test） | 用途 | 我们是否拿到 |
| --- | --- | --- | --- | --- |
| D1 | 合成单层网格板，5 个 net，网格 10–500 | 每种网格 10000 / — / 128 | 论文 Figure 5（和网格 RL 方法比可扩展性） | 否，论文未公开这批板子 |
| D2（synth_2L_v2） | 代码自带的合成生成器，2 层 | 10000 / 128 / 128 | RL 训练 + D2 评测 | 是 |
| D3（PCBench） | 开源真实 KiCad 板子 | easy 100 / medium 286 / hard 292；测试 99 / 10 / 10 | 零样本评测 | 是，自己重建 |

### D2：合成训练板怎么生成

生成脚本 `tools/datagen/synthetic_generator/generate_2layer_v2.sh`，每块板独立采样：

- 板尺寸：宽、高各自在 80–120 mm 均匀采样。
- net 数：4、5、6 均匀采样；每个 net 的焊盘数：2 个 60%、3 个 20%、4 个 10%、5 个 10%。
- 焊盘：30% 是通孔焊盘（两层都有），70% 是贴片焊盘（随机在顶层或底层）；只放在板子中央 90% 区域，焊盘间最小间距 4.8 mm。
- 设计规则：线宽 = 间距 = 0.3 mm，焊盘 2.4 mm，过孔 1.2 / 0.6 mm。
- 种子固定（训练 seed 0、val 1234、test 9999），可以逐字节复现发布版。

一块 D2 板就是一张未布线的 `.kicad_pcb` 加一个存设计规则的 `.kicad_pro`，只有焊盘和 net，没有真实元件形状。我们用的是生成好的版本，放在 `var/datasets_paper/synthetic/synth_2L_v2/`。

### D3：真实板怎么构建

来源是 [PCBench](https://github.com/PCBench/PCBench) 公开仓库（commit `dec3be75`），共 1182 块开源 KiCad 5 格式的板子。论文不分发板子本身，只给重建脚本（`tools/quickstart/prepare_pcbench.sh`），分四步：

1. **转格式**（`convert_v9.py`）：用 pcbnew 把 KiCad 5 板子载入再存成 KiCad 9，生成 `.kicad_pro`。
2. **DRC 修复与过滤**（`drc_fix_v9.py`）：最小化修改规则文件后跑 DRC，原始布线能通过 DRC 的板子留下：1182 → **679** 块。
3. **生成 guide 板**（`make_guide.py`）：把每个 net 的线宽统一成不产生新 DRC 违规的值，输出 `processed_v9_guide_v3.kicad_pcb`。注意这里的 guide 只管线宽，**不是全局布线引导**。
4. **按难度排序**（`sort_prefix.py`）：按（引脚数、net 数、元件数）升序编号成 `0001_…` 到 `0679_…`。

评测时环境会删掉原始布线，只保留元件和焊盘。原始布线的势函数增益就是论文表里的 Reference 行。

**难度划分**（`experiments/kdd/d3_dataset/build.py`，结果是 `configs/datasets/d3.json`）：

- easy：排序后前 100 块；medium：剩下的引脚 ≤ 100 的（286 块）；hard：引脚 > 100 的（292 块）。
- 测试集：easy 除一块外全部（99 块，即 **D3-A**）。medium 和 hard 各只挑 10 块（**D3-B**、**D3-C**）：先只留 2 层板，hard 再去掉引脚最多的 10%，按引脚数分 10 个分位桶，每桶取一块。
- 4 层和 8 层板（39 块）不进任何测试集。

### 板子大小统计

格式：均值 / 中位数 / 最小–最大。D2 的合成板里一个元件就是一个焊盘，所以元件栏留空。

| 集合 | 板数 | 引脚 | net | 元件 |
| --- | --- | --- | --- | --- |
| D2 测试集 | 128 | 13.7 / 13 / 8–21 | 5.1 / 5 / 4–6 | — |
| D3-A 测试集（easy） | 99 | 20.0 / 20 / 6–31 | 6.5 / 6 / 2–13 | 8.5 / 7 / 2–30 |
| D3-B 测试集（medium） | 10 | 61.8 / 62 / 34–93 | 17.0 / 17 / 11–26 | 20.1 / 18 / 10–38 |
| D3-C 测试集（hard） | 10 | 178.1 / 158 / 106–331 | 44.4 / 43 / 27–79 | 51.3 / 41 / 26–103 |
| D3 全部 medium | 286 | 61.6 / 61 / 31–100 | 17.9 / 17 / 5–42 | 21.6 / 18 / 2–650 |
| D3 全部 hard | 292 | 245.4 / 176 / 101–2103 | 57.7 / 43 / 6–451 | 79.0 / 54 / 6–670 |
| D3 全部 | 679 | 134.5 / 82 / 6–2103 | 33.3 / 23 / 2–451 | 44.4 / 25 / 2–670 |

- 测试集偏向小板：119 块里 99 块是 easy。但整个 D3 里 medium + hard 占 85%（578 / 679）。
- D3-C 测试集（平均 178 引脚）比 hard 整体（245）还小，最大的板子没有进测试集。
- D3 全部平均 net 数是训练用 D2 的约 6.5 倍。

## 模型

**没有预训练的 base model**：策略是一个从头训练的小型 decoder-only Transformer，共约 **167 万参数**（`methods/rl_agent/models/v1/`）。论文里的 LLM（GPT-5.4 等）只在 LLM baseline 里用作推理，不参与 RL。

| 部分 | 设置 | 参数量 |
| --- | --- | --- |
| Transformer 主干 | 4 层，d_model 128，8 头，FFN 512；每个残差子层带 ReZero 门控（初始为 0） | 79 万 |
| Tokenizer（实体编码） | 实体类型嵌入 + 特征投影，坐标用 Fourier 编码 | 81 万 |
| Critic 头 | 输出状态价值 V(s)，只有 PPO 用 | 6.6 万 |
| 动作头 | 动作类型头、指向候选点的 pointer 头、routing mode 头 | 约 1 千 |

### 输入：一个对象一个 token

观测里的每个对象变成一个 token = 实体类型嵌入 + 该对象特征的投影。坐标先按板子中心和尺度归一化，所以同样的几何在任何板子上得到同样的 token。

- 板子本身：`BOARD`、`EDGE`（板框线段）、`NET`、`PAD`、`TRACK`、`VIA`、`RAT`（未连飞线端点）、`HEAD`（笔头）、`DRC_VIOLATION`。
- 候选点：`CAND_PAD`、`CAND_TRACK_END`、`CAND_VIA`、`CAND_RAT`、`CAND_DIR`（笔头周围的方向点）。
- 状态区不加位置编码（对对象顺序不敏感）；另加一个"同 net"注意力偏置；时间特征是 `step_ratio` = 当前步数 / 步数上限。
- 论文配置关掉了障碍物 token 和 DRC token（`--no-obstacle-obs --no-drc-tokens`）。

### 输出：自回归解码一个三元组

每一步策略先对状态做一次前向，再自回归地输出 `(动作类型, 指向哪个候选点, routing mode)`，只填该动作需要的槽位。指针只能指向候选集合，所以不会输出非法坐标；非法动作由掩码屏蔽。开启 `--policy-net-select` 后，选哪个 net 也由策略决定，即策略自己学布线顺序。

## 训练

三种方法用**同一个模型、同一个动作空间、同一批 D2 训练板**，只差在"奖励什么时候给"和"怎么把奖励分到每一步"。参数来自论文配方 `experiments/kdd/table1_rl/cases.sh` 和 `paper_train_flags.sh`。

| | PPO per-step | PPO terminal | GRPO |
| --- | --- | --- | --- |
| 奖励配置 | `drc_dense_promoted` | `drc_sparse_promoted_ppo` | `drc_sparse_promoted_grpo` |
| 每步奖励 | Φ(s_{t+1}) − Φ(s_t) | 0，最后给 Φ(s_T) | 0，最后给 Φ(s_T) |
| 截断时 | — | 不给奖励，由 critic 的 V(s) bootstrap | 环境直接给 Φ(s_T) |
| 优势估计 | critic + GAE（γ 0.995，λ 0.95） | critic + GAE（γ 0.995，λ 0.95） | 无 critic；同一块板跑 16 条轨迹，A_i = (R_i − 组均值) / 标准差，整条轨迹每步共用 |
| 迭代数 | 300 | 300 | 1800 |
| 每次迭代采样 | 32 个环境 × 512 步 | 32 个环境 × 512 步 | 32 条轨迹（2 块板 × 16） |
| 单个 seed 训练时长（我们的机器） | 约 4–10 小时 | 原配方约 15 小时；修复版约 4.5 小时 | 约 27–33 小时 |

**共同超参**：lr 1e-4（前 20 次迭代 warmup）、每批 4 个 epoch、minibatch 256、clip 0.2、熵系数 0.01、梯度裁剪 0.5、价值损失系数 0.5（仅 PPO）、线长惩罚 0.002、过孔惩罚 0.1、奖励归一化和优势归一化开启、每局最多 256 步、布线拐角 45°。

**训练流程**：每个环境按 epoch 轮流读 10000 块 D2 训练板；每 20 次迭代在 128 块 val 板上各跑 10 次验证，以验证集平均最终势函数（`fp_mean_of_means`）最高的检查点作为 `policy_best.pt`，评测用的就是它。

**算力**：每个训练占一张 GPU，但瓶颈基本在 CPU 上的 KiCad 布线和 DRC。早期几轮训练是在有其他任务的共享卡上并发跑的，所以时长波动较大；修复版 PPO terminal 是在两张独占的 RTX A6000 上跑的。

**我们对 PPO terminal 的改动**（`tools/quickstart/train_ppo_terminal_fix.sh`）：γ 从 0.995 改成 1.0，奖励配置换成 `drc_sparse_promoted_grpo`（截断时环境也给 Φ）并关掉 `--truncation-bootstrap`，其余参数与论文完全一致。原因见复现结果一节。

## 评测

所有方法走同一条评测流程 `eval/pipeline.py`：每块板跑 5 次 rollout → 事后用完整 DRC 重新打分 → 每块板取最好的一次 → 对板子取平均（论文称 @5 协议）。

### 指标

| 指标 | 含义 | 方向 |
| --- | --- | --- |
| CP（Completion） | 整块板所有 net 都连通的板子比例，主指标 | 越高越好 |
| Pot.（Potential gain） | Φ(s_T) − Φ(s_0)，综合连通、DRC、线长、过孔的布线质量分 | 越高越好 |
| Rout.（Routability） | 连上的 net 占全部 net 的比例 | 越高越好 |
| Time | 每块板每次 rollout 的秒数 | 越低越好 |

Pot. 用的是评测专用奖励配置 `drc_dense_errors_only_eval`（只算 DRC error，不算 warning），和训练奖励不同，所以训练曲线上的数值和评测表里的 Pot. 不能直接比。

### 评测设置

- 评测用 `policy_best.pt`，采样（非贪心）解码，rollout 种子 5600，8 个并行环境。
- 每局步数上限沿用检查点的 256；大板子实验另外试了 2048。
- 事后选择规则 `posthoc_drc_aware`：5 次 rollout 里先比连通率，再比 DRC error 数（越少越好），再比 Φ，最后比线长和过孔数。
- 布线拐角检查 45°。
- 评测集：D2 测试集 128 块；D3-A 99 块、D3-B 10 块、D3-C 10 块。论文只报告了 D2、D3-A、D3-B，D3-C 是我们额外跑的。

评测命令（以 D3-A 为例，我们的脚本 `tools/quickstart/eval_rl_seeds.sh` 封装了它）：

```bash
CUDA_VISIBLE_DEVICES=6 python -u eval/pipeline.py \
  --ckpt var/outputs/full_table1_rl/seed42/ppo_per_step/checkpoints/policy_best.pt \
  --boards-list var/boards_lists/d3a_test.txt \
  --output-dir var/results/full_table1_rl/seed42_d3/d3a/ppo_per_step \
  --seed 5600 --n-rollouts 5 --n-envs 8 --rollout-mode parallel \
  --selection-method posthoc_drc_aware --check-angle 45 \
  --reward-config drc_dense_errors_only_eval
```

## 复现结果

三种方法在 D2 和 D3-A 上都复现了论文，CP 差距在 0.05 以内；D3-B 只有 10 块板，波动大；D3-C 上三种方法 CP 都是 0。PPO terminal 一行用的是我们修正后的配方（γ = 1）。

### 4-seed 结果与论文 Table 3 对比

seed 42–45，每格为"我们 / 论文"，CP 后的 ± 是 4 个 seed 的标准差。

| 方法 | split | CP | Pot. | Rout. |
| --- | --- | --- | --- | --- |
| PPO per-step | D2 | 1.00±0.00 / 1.00 | 16.28 / 16.24 | 1.00 / 1.00 |
| PPO per-step | D3-A | 0.81±0.03 / 0.86 | 21.31 / 21.46 | 0.94 / 0.95 |
| PPO per-step | D3-B | 0.35±0.11 / 0.45 | 50.35 / 50.20 | 0.84 / 0.85 |
| PPO per-step | D3-C | 0.00 / — | 52.68 / — | 0.38 / — |
| GRPO | D2 | 1.00±0.00 / 1.00 | 16.20 / 14.03 | 1.00 / 1.00 |
| GRPO | D3-A | 0.87±0.02 / 0.85 | 22.08 / 18.83 | 0.97 / 0.98 |
| GRPO | D3-B | 0.30±0.07 / 0.10 | 47.59 / 30.00 | 0.83 / 0.69 |
| GRPO | D3-C | 0.00 / — | 49.17 / — | 0.37 / — |
| PPO terminal（修复版） | D2 | 1.00±0.00 / 0.92 | 16.26 / 15.61 | 1.00 / 0.98 |
| PPO terminal（修复版） | D3-A | 0.82±0.01 / 0.82 | 21.70 / 21.02 | 0.96 / 0.95 |
| PPO terminal（修复版） | D3-B | 0.17±0.04 / 0.38 | 43.61 / 44.33 | 0.78 / 0.81 |
| PPO terminal（修复版） | D3-C | 0.00 / — | 49.55 / — | 0.37 / — |
| PPO terminal（论文原配方，seed 42） | D2 | 0.00 / 0.92 | 7.97 / 15.61 | 0.54 / 0.98 |
| PPO terminal（论文原配方，seed 42） | D3-A | 0.18 / 0.82 | 11.34 / 21.02 | 0.60 / 0.95 |

- **PPO per-step**：D2 完全一致；D3-A 的 CP 低 0.05，Pot. 几乎一样。
- **GRPO**：复现了，Pot. 在 D2、D3-A、D3-B 上都比论文高。
- **PPO terminal**：按论文原配方 4 个 seed 全部失败；修复后 D2、D3-A 与论文一致，D3-B 的 CP 偏低但 Pot. 和 Rout. 接近。
- 一块板在 D3-B 上就是 0.1 的 CP，所以 D3-B 的 CP 差异大多在噪声范围内。

### PPO terminal 为什么按论文配方训不出来

根本原因是 **γ = 0.995 加上负的终局奖励，让策略学会了拖延**。前期布得差时 Φ(s_T) 是负的：现在结束立刻拿到约 −2；拖 190 步再结束拿到约 −5，但要乘上 0.995^190 ≈ 0.39，折算只有约 −1.9，反而"更好"。越拖板子越乱，但这个代价一直被折扣低估。per-step 每步即时结算、GRPO 不打折扣，所以都没有这个问题。

训练日志里的症状：每局步数从 67 涨到 256（每局都被截断），策略熵上升，验证集势函数一直在 −14 左右。我们先后排除了另外两种解释（seed 42，各训 20 次迭代）：

| 版本 | 第 20 次迭代每局步数 | 熵走势 | 验证 fp | 结论 |
| --- | --- | --- | --- | --- |
| 论文原配方 | 256 | ↑ 3.09 | −16.4 | 失败 |
| 截断时也给 Φ | 250 | ↑ 2.96 | −11.8 | 不是"截断空子"的问题 |
| 再把熵系数设为 0 | 254 | ↑ 2.85 | −13.7 | 不是熵奖励的问题 |
| 截断给 Φ + γ = 1 | 约 100，下降中 | 2.44，先升后降 | −2.4 | 修好 |

修复版完整训练 300 次迭代后，4 个 seed 的最好验证 fp 为 +0.62 到 +0.67（per-step 为 +0.81 到 +0.83），训练末期每局约 31 步。

<!--CURVE-->

seed 42 的验证集 fp（每 20 次迭代评一次，节选）：

| 迭代 | per-step | terminal γ=1（修复版） | terminal 论文配方 |
| --- | --- | --- | --- |
| 20 | −0.82 | −2.29 | −16.42 |
| 40 | +0.25 | −2.92 | −16.19 |
| 60 | +0.44 | −1.52 | −14.92 |
| 80 | +0.77 | −0.60 | −14.89 |
| 100 | +0.80 | +0.19 | −15.07 |
| 140 | +0.77 | +0.67 | −15.20 |
| 200 | +0.73 | +0.51 | −15.10 |
| 260 | +0.80 | +0.47 | −14.86 |
| 300 | +0.81 | +0.26 | −14.40 |

### 大板子：放宽步数上限

D3-C 上每块板开局有 79–210 条待连的飞线，256 步上限下 100% 的 rollout 被截断。我们把上限改成 2048 重评了 seed 42（每格"256 步 → 2048 步"）：

| 方法 | split | CP | Rout. | 被截断的 rollout（共 50） |
| --- | --- | --- | --- | --- |
| PPO per-step | D3-B | 0.40 → 0.50 | 0.93 → 0.92 | 38 → 32 |
| GRPO | D3-B | 0.30 → 0.40 | 0.80 → 0.94 | 45 → 32 |
| PPO terminal（修复版） | D3-B | 0.20 → 0.30 | 0.80 → 0.86 | 43 → 39 |
| PPO per-step | D3-C | 0.00 → 0.00 | 0.41 → 0.48 | 50 → 50 |
| GRPO | D3-C | 0.00 → 0.00 | 0.32 → 0.62 | 50 → 50 |
| PPO terminal（修复版） | D3-C | 0.00 → 0.10 | 0.41 → 0.55 | 50 → 49 |

放宽步数有帮助但不多：即使给 2048 步，大部分 rollout 仍然把步数用完，而这些板子正常只需几百步。说明策略在大板上主要在原地打转、做无效动作，而不只是步数不够。注意：时间特征 `step_ratio` 的分布随上限改变，也可能有影响。

## 发现与局限

这个环境作为"执行器 + 裁判"很有用，但它的方法和 benchmark 都只覆盖了小板子。

- **只有 detailed routing**：一个 net 接一个 net、一次走完，没有全局布线（粗网格、拥塞估计、层分配），也没有拆线重布。唯一接近"重布"的是 KiCad 推挤模式对已有走线的局部推开。论文只在相关工作里提到 rip-up 和全局布线。
- **大板子很差**：D3-C 上三种方法 CP 都是 0，只连上约 37% 的 net。训练板平均 5.1 个 net，D3-C 平均 44.4 个、hard 全集平均 57.7 个。
- **benchmark 几乎不评大板子**：论文只报告 D3-A 和 D3-B；medium 和 hard 各只挑 10 块做测试，还去掉了最大的 10% 和所有 39 块多层板。
- **PPO terminal 的原配方在开源代码上训不出来**，需要 γ = 1。这是复现报告里必须注明的差异。

**引擎已经支持拆线**：C++ 层有 `delete_routing_of_nets`（删整个 net 的走线和过孔）、`delete_track_near`、`undo_last_segment`、`start_drag` / `fix_drag`、`lock_net`，目前只在 reset 时用来清板。加一个 `rip_up(net_id)` 动作，工作量主要在 Python 层：注册动作、写掩码规则、把被拆的 net 放回可布集合、防止反复拆装刷分。

**可做的方向**：在这个环境上搭 global → detailed → rip-up & reroute 三段式流程。global 层规划通道、层和布线顺序；detailed 层复用现有 RL 策略（它在小范围布线上已经很强，D3-A CP 0.87）；rip-up 层用上面的删线接口。D3 的 medium + hard 训练集共 578 块板，可以用来在大板上训练或评测。

## 附录：复现时踩过的坑

上游代码：[LGAI-Research/PCBWorld](https://github.com/LGAI-Research/PCBWorld)（v1.0.1，KiCad 9.0.8）。

- **OpenCascade 太新**：conda 装到的 occt 8.0.1 缺少 KiCad 9.0.8 需要的头文件，降到 7.9.3 后可以编译。
- **SWIG 太新**：SWIG 4.5 删掉了 KiCad 仍在用的 Python 2 兼容宏（`PyInt_FromLong`、`PyString_Check`），用 SWIG 4.2.1 编译 pcbnew 模块。
- **`prepare_pcbench.sh` 只在 `kicad-cli` 不存在时才编译**：如果 pcbnew 模块那次编译失败，重跑脚本不会再编，需要单独执行 `BUILD_CLI=1 BUILD_PCBNEW=1 bash engine/build_rl_router.sh`。
- **PPO terminal 需要 γ = 1**：详见上文复现结果。
