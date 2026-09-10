# ai-hedge-fund 项目功能详解（小白友好版）

---

## 1. 一句话说明这个项目是干什么的

如果完全不懂金融和量化，可以先把它理解成：

> 它想在电脑里搭一个“迷你基金公司”。

这个基金公司里面有：

```text
数据部门
  ↓
研究员
  ↓
投资策略
  ↓
组合经理
  ↓
风控
  ↓
交易执行
  ↓
账本和回测
```

这里的“研究员”既可以是模仿 Buffett、Graham 等投资风格的 LLM Agent，也可以是完全靠数学公式计算的量化模型。

所以它不是简单问大模型“这只股票能买吗”，而是试图建立：

```text
拿数据
→ 多个模型分析
→ 形成观点
→ 组合观点
→ 算仓位
→ 风控限制
→ 生成订单
→ 模拟成交
→ 记录结果
→ 历史回测
```

---

## 3. 新版核心结构：Fund → Strategy → Alpha Model

项目现在最核心的是三层：

```text
Fund
 ↓
Strategy
 ↓
Alpha Model
```

### Fund

可以理解为“整只基金”。

它会规定：

- 基金名字
- 有哪些策略
- 每个策略分多少资金
- 初始本金
- 最大单只股票仓位
- 最大总仓位
- 每天/每周/每月多久调一次仓
- 用什么指数做业绩基准

### Mandate / FundSpec

Mandate 可以理解为“这只基金长期遵守的规章制度”。

例如：

```text
本金：100 万
价值策略：60%
事件策略：40%
单只股票最多：10%
总仓位最多：100%
每周调仓
基准：SPY
```

一个很好的设计是：Mandate 不写死股票代码。

也就是说：

```text
投资方法
```

和：

```text
这一次研究哪些股票
```

是分开的。

同一个 Fund 今天可以研究 AAPL、MSFT，下一次也可以换成其他股票，策略本身不用重写。

---

## 4. Strategy：一套具体投资方法

一只 Fund 可以同时运行多个 Strategy，例如：

```text
Fund
├── Deep Value
├── Fundamental Long/Short
├── Inflections
└── Earnings Drift
```

当前仓库已经提供 4 个策略模板。

### 4.1 Deep Value

核心意思：

> 找“价格比较便宜、公司质量又不差”的股票。

使用：

- Benjamin Graham
- Warren Buffett
- Charlie Munger

其中 Graham 权重更高。

可以粗略理解为：

- Graham：重点看便宜不便宜、安全边际够不够
- Buffett：重点看是不是好公司
- Munger：重点看商业质量、竞争优势

### 4.2 Fundamental Long/Short

使用：

- Buffett
- Munger
- Graham
- Lynch
- Druckenmiller

它不是只判断某只股票“好不好”，而是把一批股票放在一起排名。

最喜欢的股票做多，最不喜欢的做空，并尽量保持 Market Neutral。

小白可以理解为：

> 不主要赌大盘涨跌，而是赌“我选的好股票会比差股票表现好”。

### 4.3 Inflections

主要用 Druckenmiller 和 Lynch。

它关注的不是“公司现在好不好”，而是：

> 公司是不是正在快速变好，或者正在快速恶化。

比如收入增速、盈利能力、业务趋势出现明显拐点。

### 4.4 Earnings Drift

这是纯量化策略，不需要 LLM。

核心模型是 PEAD（Post-Earnings Announcement Drift）。

简单说：

> 公司财报明显超预期后，市场可能不会一天之内完全消化信息，后面一段时间可能继续上涨；财报严重不及预期时则可能继续偏弱。

---

## 5. Alpha Model：统一所有“分析员”

项目把每一种能产生投资观点的方法都抽象成：

```text
AlphaModel
```

Alpha 可以粗略理解成：

> 一种试图找到“比市场平均水平更好的机会”的分析方法。

它分两类。

### LLM Agent

当前已有的投资风格包括：

- Warren Buffett
- Charlie Munger
- Benjamin Graham
- Peter Lynch
- Stanley Druckenmiller

它们不是这些真人本人，而是用 Prompt 让 LLM 按他们公开的投资理念进行分析。

### Quant Model

完全不用 LLM，通过数据和数学公式计算。

目前明确实现的代表是：

```text
PEAD
```

Roadmap 还计划 Momentum、Mean Reversion、Value/Quality Factors、Regime Detection、Statistical Arbitrage 等，但很多目前还没有完成。

---

## 6. Signal：所有分析员最后说同一种语言

无论 Buffett Agent 还是 PEAD Quant Model，最后都输出：

```text
Signal
```

最核心字段是：

```text
value ∈ [-1, +1]
```

例如：

```text
+1.0  非常看多
+0.7  比较看多
 0.0  中性
-0.6  比较看空
-1.0  非常看空
```

同时还会保存：

- reasoning
- components
- metadata

因此系统不仅知道：

```text
Buffett = +0.7
```

还可以保存：

> 为什么 Buffett 风格模型给 +0.7。

这就是可解释投资决策的基础。

---

## 7. 模型可以说“我不知道”

项目支持：

```text
abstained = true
```

代表：

> 这个模型这一次没有有效观点。

原因可能是：

- 数据不足
- LLM 调用失败
- 无法合理判断

这和 `0 = 中性` 不一样。

Portfolio 合并观点时会排除 abstain，避免“没回答”被误当成“认真分析后的中性意见”。

---

## 8. Portfolio Construction：把意见变成仓位

Alpha Model 只负责发表观点，不负责直接决定买多少钱。

例如：

```text
Buffett：AAPL +0.8
Munger：AAPL +0.6
Graham：AAPL +0.3
```

Portfolio 模块会先把多个 Signal 按模型权重融合，再转换成目标仓位。

当前使用的核心方法比较简单：

```text
Conviction Weighted
```

可以理解为：

> 综合看多程度越强，分到的仓位越高。

当前还不是成熟的 Mean-Variance、Black-Litterman、HRP、CVaR 等组合优化系统，因此后面接 PyPortfolioOpt 很有价值。

---

## 9. Market Neutral

Portfolio 支持：

```text
market_neutral = true
```

普通策略可能只是：

```text
看好的买
不看好的不买
```

Market Neutral 则可以：

```text
最看好的 → 做多
最不看好的 → 做空
```

尽量让：

```text
多头金额 ≈ 空头金额
```

这样更侧重验证“选股能力”，减少整个大盘涨跌的影响。

---

## 10. Multi-Strategy：一只基金可以同时跑多个策略

例如：

```text
Alpha Fund
├── Deep Value       40%
├── Fundamental L/S  30%
└── Earnings Drift   30%
```

每个策略：

```text
独立调用自己的 Alpha Models
→ 得到自己的目标组合
```

然后 Fund 再按资金份额把多个策略组合起来：

```text
Strategy A
+
Strategy B
+
Strategy C
→
最终总组合
```

这是新版比单纯 Agent 投票更像真实基金系统的地方。

---

## 11. Risk：风控可以直接压住 Agent

项目非常强调：

> LLM 只能发表观点，不能直接控制最终资金。

流程是：

```text
LLM / Quant
→ Signal
→ Portfolio
→ Risk
→ Order
```

Risk 使用确定性代码。

### 当前主要硬限制 1：最大单股仓位

```text
max_position_pct
```

例如设为 10%，即使 Agent 强烈建议 30%，也会被压到 10%。

### 当前主要硬限制 2：最大总风险敞口

```text
max_gross_exposure
```

控制全部仓位绝对值之和。

如果组合超过上限，就同比例缩小。

### 风控会留下记录

每次触发限制会产生 `ClampEvent`。

例如：

```text
AAPL
原目标：25%
风险上限：10%
最终：10%
```

因此以后可以解释为什么某个观点没有被完全执行。

---

## 12. run_cycle：整个项目真正的主流程

当前最核心函数是：

```text
run_cycle()
```

可以理解成：

> 让基金“上班一次”。

一次 Cycle 大致做：

```text
1. 获取最新可用价格
2. 读取当前现金和持仓
3. 计算当前资产
4. 每个 Strategy 开始工作
5. 每个 Strategy 调用 Alpha Models
6. Alpha Models 输出 Signals
7. 每个 Strategy 组合自己的 Signals
8. 多个 Strategy 的仓位合并
9. Master Risk 检查最终组合
10. 计算需要买卖多少
11. Broker 模拟执行
12. 更新现金和持仓
13. 计算 NAV
14. 生成完整 CycleRecord
```

对我们来说，这条 Pipeline 是最值得保留的基础骨架。

---

## 13. DataClient：数据源可以替换

新版专门定义了：

```text
DataClient
```

可以理解成一套“统一插头”。

当前接口涉及：

- 历史价格
- 财务指标
- 公司新闻
- 内部人交易
- 公司基本事实
- Earnings
- Earnings History
- Market Cap

上层 Strategy 和 Alpha Model 不需要知道数据到底来自哪个网站。

这对我们接 A 股非常重要。

未来可以做：

```text
AkshareDataClient
```

只要实现统一接口：

```text
AKShare
→ DataClient
→ Alpha/Strategy/Portfolio/Risk
```

后面的模块理论上不用跟着全部重写。

---

## 14. Point-in-Time：回测不能偷看未来

这是项目非常强调的金融正确性原则。

假设回测：

```text
2023-03-01
```

系统只能看到 2023-03-01 当时已经正式公开的数据。

不能因为今天数据库里已经有 2023 年全年财报，就把未来财报塞给过去的模型。

否则会产生：

```text
Lookahead Bias
未来函数
```

项目明确要求财务数据按实际披露日期过滤，而不是简单按财报所属季度过滤。

这个原则后续必须保留。

---

## 15. Fail Loud：系统故障必须真的报错

如果出现：

- API Key 错误
- 网络失败
- Rate Limit
- 服务器错误

Data Provider 应该抛出异常。

不能偷偷：

```text
return []
```

因为空数组在金融回测中可能被理解为：

> 今天真的没有数据，所以没有交易信号。

项目明确区分：

```text
真正没有数据 → empty
基础设施失败 → exception
```

这个工程设计很好。

---

## 16. 数据缓存

API 响应会缓存到：

```text
~/.hedge-fund/cache/
```

作用：

- 减少重复 API 请求
- 节省费用
- 提升回测速度
- 让重复实验使用相同历史数据
- 缓存预热后可以减少联网依赖

---

## 17. LLM Provider

项目没有绑定单一大模型。

当前支持：

- Anthropic
- OpenAI
- DeepSeek
- Google
- xAI
- Kimi

统一通过：

```text
make_llm()
```

创建模型客户端。

因此换模型时不需要重写全部投资 Agent。

---

## 18. LLM Prompt Cache

如果同一股票、同一日期、同一 Agent 的请求被重复调用，项目会利用 Prompt Cache 降低重复请求。

这对回测尤其重要，因为：

```text
5 个 Agent
× 100 只股票
× 几百个历史日期
```

会产生非常大的 LLM 调用量。

---

## 19. Features：基本面时间点快照

当前 `features/` 已有：

```text
Point-in-Time Fundamentals Snapshot
```

意思是：

> 把某一天当时真正可见的财务信息整理成统一快照。

多个 LLM Agent 可以共用同一份经过整理的数据。

这个模块当前仍属于部分完成状态。

---

## 20. Broker：一个假的证券账户

项目定义统一的：

```text
Broker
```

当前正式实现的是：

```text
SimBroker
```

它保存：

- Cash
- Positions

收到买单：

```text
股票增加
现金减少
```

收到卖单：

```text
股票减少
现金增加
```

但不会真的连接券商。

---

## 21. Execution：从目标仓位算出买卖订单

例如：

```text
当前 AAPL：5%
目标 AAPL：10%
```

系统要算：

> 还需要买多少股？

如果：

```text
当前：15%
目标：8%
```

则计算要卖多少。

因此：

```text
Target Weight
+ Current Position
+ Price
→ Buy/Sell Orders
```

---

## 22. 当前模拟交易仍然比较简单

现在的 SimBroker 基本是：

> 按给定价格直接成交。

目前没有完整模拟：

- 滑点
- Bid/Ask Spread
- 手续费
- 印花税
- 流动性
- 部分成交
- 成交失败
- A 股 T+1
- 涨跌停
- 停牌
- 一手 100 股

因此它适合验证系统架构，但不能直接作为严肃 A 股交易回测器。

---

## 23. Backtesting：基金级历史回测

项目已经实现 Fund-level Backtest。

流程：

```text
设置开始日期、结束日期、股票池
↓
按照 Fund 的调仓周期生成日期
↓
每个日期调用一次 run_cycle
↓
持仓和现金持续延续
↓
得到完整净值曲线
```

不是每个回测日都重新拿初始资金开始。

这意味着 Day 1 的持仓会延续到 Day 2，再按新目标调仓。

---

## 24. 当前支持的调仓频率

```text
daily
weekly
monthly
```

例如：

- daily：每天调仓
- weekly：每周最后一个交易日调仓
- monthly：每月最后一个交易日调仓

频率直接属于 Fund Mandate。

---

## 25. 回测输出指标

当前包括：

- Total Return
- Annualized Return
- Sharpe Ratio
- Max Drawdown
- Benchmark Return
- Excess Return
- Number of Cycles
- Number of Orders

小白解释：

### Total Return
100 万变 120 万，总收益就是 20%。

### Annualized Return
把不同长度投资期换算成大约每年的收益率。

### Sharpe Ratio
粗略看“承担这些波动换来的收益值不值”。

### Max Drawdown
历史上从高点到低点最惨的一次跌了多少。

### Benchmark Return
例如同期 SPY 涨了多少。

### Excess Return

```text
基金收益 - 基准收益
```

用来判断复杂策略是否真的比直接买指数更有价值。

---

## 26. 回测和未来运行使用同一条 Pipeline

这是项目最值得保留的原则之一：

```text
Backtest
= 历史时间 + SimBroker

未来 Paper
= 当前时间 + PaperBroker

未来 Live
= 当前时间 + RealBroker
```

核心都调用：

```text
run_cycle
```

这样尽量避免：

> 回测代码是一套，真正运行又是另一套。

目前真正完成的是 Backtest 和单次“run today”；完整 Paper/Live 还没有完成。

---

## 27. Event Study：研究某个事件以后股票到底怎么走

项目还实现了：

```text
Event Study
```

目前重点围绕财报事件。

例如研究：

> 公司公布超预期财报后，未来 1、3、5、10 天是否真的比大盘表现更好？

它会计算：

```text
Abnormal Return
CAR
```

CAR 可以理解成：

> 扣除大盘自己的涨跌之后，这只股票因为这个事件额外产生的表现。

还支持：

- 多只股票
- 多次财报事件
- 平均 CAR
- t-test
- bootstrap confidence interval

这是验证量化假设有没有统计依据的研究工具。

---

## 28. TUI：终端里的可视化操作界面

运行：

```bash
aihf
```

会进入 Textual TUI。

当前可以用于：

- 创建 Fund
- 选择股票
- 选择 Strategy
- 设置调仓频率
- 保存 Mandate
- 运行当前 Cycle
- 运行 Backtest
- 查看净值曲线
- 浏览 Fund History
- 选择 LLM Model
- 配置 API Key
- 查看 Signal Thesis

Mandate 默认保存到：

```text
~/.hedge-fund/mandates/
```

---

## 29. CLI：也可以给程序直接调用

例如：

```bash
aihf mandate.yaml --tickers AAPL,MSFT
```

运行一次 Fund Cycle。

或者：

```bash
aihf mandate.yaml --tickers AAPL,MSFT --backtest
```

执行回测。

完整结果可以输出 JSON。

这对未来 Java Backend 调 Python Investment Core 很有参考价值。

---

## 30. CycleRecord：每次投资决策都会留下“收据”

每次 run_cycle 都产生：

```text
CycleRecord
```

会保存：

- Fund
- 日期
- 股票池
- 价格
- 被跳过的股票
- 每个 Strategy
- 每个 Alpha Model 的 Signal
- Conviction
- Strategy Weight
- 原目标仓位
- Risk Clamp
- 最终仓位
- Orders
- Fills
- Positions
- Cash
- NAV

因此系统不仅知道：

> 最后赚了多少钱。

还可以追溯：

> 当时为什么形成这个仓位。

---

## 31. Persistent Ledger：目前只完成一半

项目未来想让 Fund 真正“活着”。

例如：

```text
今天运行后持有 AAPL
↓
程序关闭
↓
明天重新启动
↓
仍然知道昨天的现金和持仓
```

目前“写入每次 CycleRecord”已经有了。

但是“下次运行自动读取上一次账户状态并继续”仍在完善。

所以当前单次 run-today 还不是完整的常驻基金。

---

## 32. 当前已实现 / 部分实现 / 计划中

### 已实现

```text
DataClient Protocol
数据 Provider Client
Disk Cache

AlphaModel
Signal

PEAD
Buffett
Munger
Graham
Lynch
Druckenmiller

FundSpec
StrategySpec
Mandate YAML

4 个 Strategy

Portfolio Construction

单股仓位限制
Gross Exposure 限制

Broker Protocol
SimBroker

run_cycle
Fund-level Backtest
Event Study

TUI
CLI

多 LLM Provider
```

### 部分实现

```text
Point-in-Time Data
Persistent Fund
Persistent Ledger
Features
Risk System
Allocator
Broker System
TUI
```

### Roadmap 中，还不能当成现成功能

```text
Paper Broker
真实 Broker

Scheduler / Daemon
自动定时运行

完整 Observability

Research Lab 自动化
Strategy Generator

CPCV
PBO
回测过拟合验证

Momentum
Mean Reversion
Factor Model
Regime Detection
Statistical Arbitrage

动态 CIO Allocator

完整 Web Dashboard

自然语言控制 Fund

Alternative Data
```

---

## 33. Validation：未来防止“回测特别漂亮但其实是碰巧”

当前：

```text
validation/
```

基本还是骨架。

未来计划 CPCV 和 PBO。

简单理解：

如果你试了 1000 个策略，最后总能找到一个历史收益特别好的。

这个“最好策略”有可能只是碰巧适合那段历史，而不是未来真的有效。

Validation 就是用来检测：

```text
Backtest Overfitting
回测过拟合
```

这一层以后非常重要。

---

## 34. 这个项目做得好的地方

### 34.1 AI Agent 和 Quant Model 统一

```text
Buffett Agent
PEAD Quant
未来 Qlib Model
↓
统一输出 Signal
```

不会形成两套完全割裂的系统。

### 34.2 LLM 不直接控制资金

```text
LLM → 观点
代码 → 仓位
Risk → 最终限制
```

比让 LLM 直接说“买 80%”可靠很多。

### 34.3 Backtest 和运行时共用 run_cycle

减少研究代码和未来实际运行逻辑不一致。

### 34.4 Point-in-Time 意识很强

明确关注财务数据的真实披露时间，这是金融回测中很关键的正确性要求。

### 34.5 模块边界比较清楚

已经有明确的：

```text
DataClient
AlphaModel
Signal
StrategySpec
FundSpec
Broker
RiskLimits
```

后续换 AKShare、接 Qlib、接 PyPortfolioOpt 相对容易。

---

## 35. 当前明显不足

### 35.1 A 股基本未支持

缺少完整：

- 沪深代码体系
- 前复权/后复权
- A股交易日历
- T+1
- 涨跌停
- 停牌
- 一手100股
- 印花税
- ST/退市规则
- 中国财报字段
- 中国宏观数据

### 35.2 数据源偏单一

当前主要围绕 Financial Datasets。

我们以后还需要 AKShare、基金/ETF 数据、新闻、宏观以及可能的商业授权数据源。

### 35.3 Quant 能力还比较薄

当前真正完成的纯 Quant 代表主要是 PEAD。

我们的系统还需要 Momentum、Value、Quality、Growth、Volatility、Factor Ranking、ML、Qlib 等。

### 35.4 Portfolio Optimization 比较简单

当前主要是 Conviction Weighted。

后续仍需要：

- Mean-Variance
- Black-Litterman
- HRP
- CVaR
- Risk Parity
- Constraints

### 35.5 Risk 还比较基础

目前最核心的是单股上限和总仓位上限。

未来还应增加：

- Volatility
- Drawdown
- Industry Concentration
- Liquidity
- Correlation
- VaR/CVaR
- Stress Test
- User Risk Profile
- Data Quality Risk
- Confidence Risk

### 35.6 没有真正的公募基金/ETF分析引擎

这里的 `Fund` 指“对冲基金运行实体”，不是中国公募基金。

所以当前没有：

- 基金经理分析
- 基金持仓分析
- 基金风格
- 基金评分
- ETF Tracking Error
- ETF Premium/Discount
- ETF Liquidity

这些需要我们后续自研。

### 35.7 深度 Research 不够

相较 TradingAgents / FinRobot，目前还缺成熟的：

- Technical Analyst
- News Analyst
- Macro Analyst
- Bull/Bear Debate
- 深度 Valuation
- Evidence Synthesis
- Research Report

因此 TradingAgents 和 FinRobot 后续仍然有接入价值。

---

## 43. 功能成熟度总表

| 功能 | 当前情况 | 评价 |
|---|---|---|
| Fund 架构 | 已有 | 很值得保留 |
| Mandate | 已有 | 很适合扩展 |
| Multi-Strategy | 已有 | 很重要 |
| LLM Alpha | 已有 | 可扩展 |
| Quant Alpha | 少量 | 明显不足 |
| Signal Contract | 已有 | 很好 |
| Portfolio | 已有 | 但比较简单 |
| Risk | 已有 | 但基础 |
| Data Adapter | 已有 | 很好 |
| Point-in-Time | 部分 | 原则很好 |
| Cache | 已有 | 实用 |
| SimBroker | 已有 | 真实市场模拟不足 |
| Execution | 基础已有 | 需要 A 股化 |
| Fund Backtest | 已有 | 很重要 |
| Event Study | 已有 | 很有价值 |
| 多 LLM | 已有 | 比较完善 |
| TUI | 已有 | 调试方便 |
| CLI | 已有 | 易于系统集成 |
| Persistent Ledger | 部分 | 还需开发 |
| Paper Trading | 未完成 | Roadmap |
| Live Trading | 未完成 | Roadmap |
| Validation | 未完成 | 后面必须补 |
| Scheduler | 未完成 | Roadmap |
| A股 | 基本没有 | 我们重点改造 |
| 公募基金分析 | 没有 | 我们自研 |
| ETF Engine | 没有 | 我们自研 |

---

- 

## 新增：A 股数据源适配（ashare_extension）

本项目现已增加独立的 `ashare_extension/` 扩展层，用于将最新
`A_Share_investment_Agent` 中的 A 股数据能力接入当前 `hedge_fund` v2
的数据协议。该章节为新增说明，前文原始内容保持不变。

### 代码位置

- `ashare_extension/data/baostock_client.py`：迁移 BaoStock 登录、沪深代码转换、历史日线和交易日历查询。
- `ashare_extension/data/akshare_cache.py`：迁移 AkShare 实时行情、财务指标、新闻和 BaoStock 历史行情的 SQLite 缓存、TTL、增量刷新、去重及 upsert 逻辑。
- `ashare_extension/data/sqlite_cache.py`：迁移 A_Share 的轻量 SQLite 缓存实现，支持自动建表、补列和按主键更新。
- `ashare_extension/network/proxy_manager.py`：迁移代理轮询、直连 fallback、重试和指数退避。
- `ashare_extension/data/client.py`：新增薄适配器 `AShareDataClient`，把上述 DataFrame 转换为 `hedge_fund.data.models` 中的 `Price`、`FinancialMetrics`、`CompanyNews` 和 `CompanyFacts`。
- `ashare_extension/cli.py`：独立命令行数据检查入口，不覆盖原有 `aihf` 命令。

### 支持的数据接口

```python
from ashare_extension import AShareDataClient

with AShareDataClient(adjust="qfq") as client:
    prices = client.get_prices("600519", "2024-01-01", "2024-12-31")
    metrics = client.get_financial_metrics("600519", "2024-12-31", limit=4)
    news = client.get_news("600519", "2024-12-31", "2024-01-01", limit=20)
    market_cap = client.get_market_cap("600519", "2024-12-31")
```

也可以运行：

```powershell
python -m pip install -r ashare_extension/requirements.txt
python -m ashare_extension.cli 600519 --start 2024-01-01 --end 2024-12-31 --kind all
```

历史行情使用 BaoStock，实时行情、财务指标和新闻使用 AkShare，缓存默认写入
`data/market_data_cache.db`，可通过 `MARKET_CACHE_DB_PATH` 修改。代理相关环境变量沿用
A_Share 项目的 `AKSHARE_PROXY_*` 配置。仓库内的 `akshare/` 源码会在环境未安装
AkShare 时作为本地候选路径按需加载。

### 协议边界和空值语义

`AShareDataClient` 实现 `hedge_fund.data.protocol.DataClient`，因此可直接传给当前
项目的 pipeline、信号和回测函数，无需修改这些原始模块。A 股数据源不提供 SEC
内幕交易和 SEC earnings 对象，`get_insider_trades`、`get_earnings` 和
`get_earnings_history` 分别返回空列表或 `None`，不伪造美股数据。

### 原始文件修改标记

本次 A 股适配没有修改 `hedge_fund/` 包内原始代码，也没有修改本文件已有章节；新增
代码全部位于 `ashare_extension/`。工作区中此前存在的 `hedge_fund/fund/spec.py`
编码修复和 `hedge_fund/llm/api_models.json` 模型登记变更与本次适配无关，未在本章节
中重述。

### 真实网络配置补充

在 `scrapy312` 环境中已持久化以下 AkShare 配置：

```text
AKSHARE_PROXY_FORCE_DIRECT=false
AKSHARE_PROXY_LIST=http://127.0.0.1:7897,direct
AKSHARE_PROXY_ALLOW_DIRECT=true
AKSHARE_PROXY_MAX_ATTEMPTS=3
AKSHARE_PROXY_BASE_DELAY=1
AKSHARE_PROXY_MAX_DELAY=15
AKSHARE_PROXY_JITTER=0.5
```

扩展层会把 `AKSHARE_PROXY_LIST` 的第一个非 `direct` 地址用于 BaoStock 的
HTTP CONNECT 隧道，也支持 `socks5://` 地址；可以用 `BAOSTOCK_PROXY` 单独覆盖。
旧版主机 `www.baostock.com:10030` 在当前网络中不可用，因此 BaoStock 使用新版
公共主机 `public-api.baostock.com:10030`，无需通过 AkShare 的 HTTP 代理转发。

后续验证发现 BaoStock `0.9.3` 已将服务主机切换为 `public-api.baostock.com`，
并要求客户端版本 `00.9.00` 以上。适配器默认使用该主机，也支持通过
`BAOSTOCK_SERVER_IP` 覆盖；`scrapy312` 已安装 `baostock 0.9.3`，BaoStock
连接采用直连，AkShare 继续使用 `127.0.0.1:7897` HTTP 代理。

## 新增：A 股数据源适配补全

本节继续补充 `A_SHARE_UPDATE_ANALYSIS.md` 第 1 节的剩余功能。新增实现仍全部位于
`ashare_extension/`，没有修改 `hedge_fund/` 包内任何文件。

### 新增数据能力

- `ashare_extension/data/market_snapshot.py`：迁移原 A 股项目的市场快照入口和 SQLite
  缓存结构，并将数值来源改为真实数据。快照统一返回实时价、涨跌幅、成交量、成交额、
  5 日均量、52 周高低点、总市值、流通市值、PE、PB、TTM PS 和各档资金净流入。
- `ashare_extension/data/market_analysis.py`：迁移原 `macro_news_agent` 的沪深 300 输出
  结构，使用 BaoStock 的 `sh.000300` 历史数据计算 20/60 日动量、20/60 日均线、
  波动率、市场评分、方向信号、主要驱动和风险。可选传入 v2 `LLMClient` 增强文字总结。
- `ashare_extension/data/akshare_cache.py`：增加个股资金流缓存和 TTM 营收计算。东方财富
  资金流保持 AkShare 的字段结构；针对当前代理拒绝 HTTPS CONNECT 的情况，使用同一
  东方财富接口的 HTTP 兼容路径并继续复用 `ProxyManager` 的代理轮询与重试。
- `ashare_extension/data/stock_basic.py`：新增完整 `get_stock_basic()`，不再只暴露中文名称。
- `ashare_extension/data/client.py`：新增 `get_realtime_quote()`、`get_fund_flow()`、
  `get_financial_report()`、`get_financial_statements()`、`get_stock_basic()`、
  `get_market_snapshot()` 和 `get_csi300_analysis()`；原 `get_financial_metrics()` 已补齐
  `price_to_earnings_ratio`、`price_to_book_ratio` 和 `price_to_sales_ratio`。

实时单股行情优先使用腾讯单股行情接口，并转换成 AkShare 中文字段格式；这是因为当前
网络下东方财富全市场实时表下载容易被远端断开。财务指标、三大报表和新闻仍由 AkShare
提供，历史 K 线和交易日历仍由 BaoStock 提供。

### 代码和日期规范

输入同时支持 `600519`、`sh.600519`、`SH600519` 等格式，并补充北京证券交易所
`bj.` 格式。`000300`、`沪深300`、`沪深300指数` 和 `CSI300` 均规范化为
BaoStock 的 `sh.000300`。

历史日期的市场快照不会混入当前实时市值和估值，避免回测前视偏差；实时日期使用最新
行情。PS 使用累计财报计算 TTM 营收，而不是直接使用半年度或前三季度累计营收。

### BaoStock 慢响应保护

扩展层为 BaoStock 官方客户端增加了本地 socket 读取超时和失败重连，不修改安装目录中
的第三方包。`scrapy312` 已持久化：

```text
BAOSTOCK_SOCKET_TIMEOUT=15
BAOSTOCK_MAX_ATTEMPTS=3
```

真实测试中首次交易日请求曾返回 `10002007`，适配器关闭失效连接并重新登录后成功完成
完整快照，验证了恢复路径。

### 公共调用示例

```python
from ashare_extension import AShareDataClient

with AShareDataClient() as client:
    basic = client.get_stock_basic("600519")
    statements = client.get_financial_statements("600519", "2026-09-09")
    flow = client.get_fund_flow("600519", "2026-09-09", limit=20)
    snapshot = client.get_market_snapshot("600519", "2026-09-09")
    csi300 = client.get_csi300_analysis("2026-09-09")
```

### 原始文件修改标记

本次补全没有修改 `hedge_fund/`。根目录 `pyproject.toml` 和原有命令入口也未修改，新增
能力通过 `ashare_extension` 的 Python API 和 `python -m ashare_extension.cli` 暴露，
因此后续合并上游 `ai-hedge-fund` 更新时不需要解决 A 股功能与核心包的代码冲突。

## 新增：A 股 SQLite 缓存风险优化

本次优化继续遵守扩展层隔离原则，全部实现位于 `ashare_extension/`，没有修改
`hedge_fund/` 原始代码。

### 两级缓存策略

`CachedAShareDataClient` 将缓存职责明确分开：历史标准接口可以使用
`hedge_fund.data.CachedDataClient` 的 JSON 缓存；当日及未来日期不进入该永久缓存，
而是由 A 股 SQLite 缓存的 TTL 控制。这样既保留历史回测的离线复现能力，也避免实时
行情被外层无 TTL 缓存长期遮蔽。

```python
from ashare_extension import CachedAShareDataClient

with CachedAShareDataClient() as client:
    prices = client.get_prices("600519", "2025-01-01", "2025-12-31")
    quote = client.get_realtime_quote("600519")
    snapshot = client.get_market_snapshot("600519")
```

传入 `refresh=True` 可同时绕过 JSON 和 SQLite 缓存；各扩展方法仍支持单次
`force_refresh=True`。该包装器保留 `get_market_snapshot()`、`get_fund_flow()`、
`get_financial_statements()` 和 `get_csi300_analysis()`，不会出现通用
`CachedDataClient` 包装后 A 股专用方法不可见的问题。

### 历史数据安全

`AShareDataClient.get_market_cap()` 仅在目标日期为今天或未来时使用实时总市值。
历史日期暂时返回 `None`，直到能够从目标日期可获得的总股本和收盘价可靠计算历史市值，
从而避免回测前视偏差。

### SQLite 并发保护

`AkshareSQLiteCache` 对同一数据库路径共享进程内写锁，并使用 WAL、原子写事务、
SQLite `busy_timeout` 和指数退避重试处理并发写入。环境变量
`MARKET_CACHE_SQLITE_TIMEOUT` 控制锁等待秒数，默认 30 秒。测试覆盖多缓存实例并发写入
和外部连接暂时持有写锁后恢复的场景。

### 原始文件修改标记

本次没有修改 `hedge_fund/` 下的任何文件。新增或修改内容仅涉及
`ashare_extension/data/`、`ashare_extension/tests/` 和扩展说明文档。

扩展 CLI 已改用 `CachedAShareDataClient`，执行
`python -m ashare_extension.cli 600519 --kind all --refresh` 可以在单次运行中绕过两层缓存。
