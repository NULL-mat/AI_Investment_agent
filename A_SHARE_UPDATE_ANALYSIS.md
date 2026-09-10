# A_Share_investment_Agent 功能更新分析

本文对比两个本地仓库：

- 当前项目：`AI_Investment_agent`，当前 `ai-hedge-fund` 的 `hedge_fund/` v2 架构，HEAD 为 `fc1bf25`
- 对比项目：`A_Share_investment_Agent`，远程仓库为 `24mlight/A_Share_investment_Agent`，HEAD 为 `d65f618`

## 结论

`A_Share_investment_Agent` 不是当前 `ai-hedge-fund` v2 的简单补丁，而是基于早期 `src/ + LangGraph` 架构发展出来的 A 股专用分支。它主要增强了 A 股数据、新闻检索、缓存、宏观分析、辩论室、回测、可观测性和 Web API 等能力。

由于两个项目的核心抽象已经不同，不能直接把整个 A_Share 项目当成当前项目的增量版本合并。

## 1. A 股数据源适配

A_Share 将早期项目偏美股的数据链路改造成中国 A 股专用链路：

- 引入 AkShare 获取 A 股行情和财务数据
- 引入 BaoStock 获取历史 K 线和交易日数据
- 支持 A 股股票代码和中文股票名称
- 增加股票基本信息查询
- 增加沪深 300（`000300`）市场级分析
- 将实时行情、资金信息和估值数据统一到市场快照

主要代码：

- `src/tools/akshare_cache.py`
- `src/tools/baostock_client.py`
- `src/tools/market_snapshot.py`
- `src/tools/stock_basic.py`

相关提交：

```text
3fb8db7 价格链路切换到 BaoStock
39354fc 集成 BaoStock 数据源
8ce8afc 修复数据源
```

## 2. SQLite 数据缓存层

项目增加了 `data/market_data_cache.db` SQLite 缓存，缓存内容包括：

- 实时行情、财务指标和三大报表
- 历史日线行情
- 股票新闻
- LLM 生成的市场快照
- 宏观新闻摘要

缓存层提供 TTL、增量缓存、缺失交易日补齐、自动建表/补列、去重、upsert、历史数据长期保存和强制刷新开关。

主要代码：

- `src/tools/akshare_cache.py`
- `src/database/sqlite_cache.py`

相关提交：

```text
137281f 加固 AkShare 数据层，增加代理轮询与缓存管控
7fc4b81 优化 AkShare 数据层和缓存系统
c04a587 重构缓存逻辑并支持强制刷新
```

## 3. 代理轮询和网络重试

针对 AkShare、BaoStock 和新闻服务容易出现网络断开、代理错误等问题，项目增加了：

- 多代理轮询和直连 fallback
- 最大重试次数
- 指数退避和随机抖动
- 统一的请求包装器

主要代码：`src/network/proxy_manager.py`、`src/tools/akshare_cache.py`。

相关配置：

```env
AKSHARE_PROXY_LIST=direct
AKSHARE_PROXY_MAX_ATTEMPTS=3
AKSHARE_PROXY_BASE_DELAY=1
AKSHARE_PROXY_MAX_DELAY=15
AKSHARE_PROXY_JITTER=0.5
AKSHARE_PROXY_ALLOW_DIRECT=true
```

## 4. 新闻系统重构

A_Share 对新闻系统进行了大幅扩展：

- 集成 Tavily 新闻搜索 API
- 支持 Google 搜索和网页抓取 fallback
- 支持中文财经新闻搜索
- 股票名称与代码联合查询
- 按 Agent 类型生成定制查询
- 新闻数量限制和日期窗口过滤
- 搜索结果去重、增量缓存
- 新闻来源、URL 和发布时间标准化
- Tavily `include_domains` / `exclude_domains` 支持

主要代码：

- `src/tools/news_crawler.py`
- `src/tools/news_query_builder.py`
- `src/crawler/news_search/base.py`
- `src/crawler/news_search/tavily_impl.py`

相关提交：

```text
eec3439 增加 Google 搜索和日期过滤
1af11b9 优化新闻检索和缓存
09c71a2 优化新闻爬虫和查询构建器
da305de 增加新闻数量配置
d65f618 重构新闻查询构建器，支持 Tavily API
```

## 5. 宏观分析链路

项目增加了两个宏观 Agent：

- `macro_analyst_agent`：分析行业、政策和宏观经济
- `macro_news_agent`：分析沪深 300 和市场级新闻

股票新闻和市场宏观新闻可以并行获取，最后汇总到 Portfolio Manager。主要代码是 `src/agents/macro_analyst.py`、`src/agents/macro_news_agent.py` 和 `src/main.py`。

相关提交：

```text
4c1c364 增加宏观分析师 Agent
1a9ad15 增加宏观新闻 Agent 并行流程
59f9e2a 增强宏观新闻缓存可靠性
```

## 6. 多空研究员和辩论室

A_Share 增加了：

```text
researcher_bull_agent
researcher_bear_agent
debate_room_agent
```

工作流变为：

```text
市场数据
  ├── 技术分析
  ├── 基本面分析
  ├── 情绪分析
  ├── 估值分析
  └── 宏观新闻

四类股票分析
  ├── 多头研究员
  └── 空头研究员

多空研究员 → 辩论室 → 风险管理 → 宏观分析 → 组合管理
```

辩论室增加了 LLM 第三方评估、多空置信度计算，以及传统信号与 LLM 评分的混合决策。

主要代码：`src/agents/researcher_bull.py`、`src/agents/researcher_bear.py`、`src/agents/debate_room.py`、`src/main.py`。

相关提交：

```text
064bb3b v2
63da611 增强辩论室 LLM 决策
0dd1f45 增加 LLM 辩论决策和 OpenAI 兼容配置
```

## 7. 风险管理增强

风险管理 Agent 增加了：

- 年化波动率、95% VaR、最大回撤
- 波动率分位数和市场风险评分
- 压力测试
- 当前持仓市值和最大允许仓位
- 基于风险等级的买卖限制

组合管理综合技术、基本面、情绪、估值、风险、宏观和市场新闻信号，输出操作方向、数量、置信度和中文分析报告。

主要代码：`src/agents/risk_manager.py`、`prompts/portfolio_manager/system.md`。

## 8. Gemini 和 OpenAI Compatible 双通道

项目增加了 LLM 客户端工厂，支持：

```env
GEMINI_API_KEY=
GEMINI_MODEL=
OPENAI_COMPATIBLE_API_KEY=
OPENAI_COMPATIBLE_BASE_URL=
OPENAI_COMPATIBLE_MODEL=
```

同时增加了统一消息格式、指数退避、多次重试和 API 失败 fallback。

主要代码：`src/utils/llm_clients.py`、`src/tools/openrouter_config.py`。

当前 `ai-hedge-fund` v2 的 provider registry 更统一，已经支持 Anthropic、OpenAI、DeepSeek、Google、xAI、Kimi；A_Share 的优势是直接适配 OpenAI 兼容中转站。

## 9. FastAPI 后端服务

A_Share 新增了完整的 FastAPI 后端：

- 后台线程执行分析任务
- 分析任务状态和结果查询
- Agent 状态、输入、输出和推理查询
- LLM 请求与响应查询
- 工作流状态和历史运行查询
- 工作流流程数据
- Swagger/OpenAPI 文档

主要代码：

- `backend/main.py`
- `backend/routers/analysis.py`
- `backend/routers/agents.py`
- `backend/routers/workflow.py`
- `backend/routers/runs.py`
- `backend/routers/logs.py`

主要接口：

```text
POST /api/analysis/start
GET  /api/analysis/{run_id}/status
GET  /api/analysis/{run_id}/result
GET  /api/agents/
GET  /api/agents/{agent_name}/latest_input
GET  /api/agents/{agent_name}/latest_output
GET  /api/agents/{agent_name}/reasoning
GET  /api/workflow/status
GET  /api/runs/
GET  /api/runs/{run_id}/flow
GET  /logs/
```

默认日志存储是内存存储，服务重启后会丢失。

## 10. Agent 和 LLM 可观测性

项目增加了 Agent 执行日志和 LLM 交互日志。

Agent 执行日志记录 Agent 名称、运行 ID、开始/结束时间、输入状态、输出状态、推理详情和终端输出。

LLM 交互日志记录请求消息、响应消息、Agent 名称、运行 ID 和时间戳。

此外还支持回测 trace 目录、JSON/JSONL 文件落盘和 Agent 状态追踪。

主要代码：

- `src/utils/api_utils.py`
- `src/utils/trace_logger.py`
- `src/utils/agent_trace_filter.py`
- `backend/schemas.py`
- `backend/state.py`

## 11. 回测系统增强

A_Share 的回测系统增加或明确支持：

- 初始持仓和初始资金
- 使用开盘价成交
- 每日决策记录
- LLM 决策 JSONL
- 回测日志目录和回测图表
- 交易结果汇总
- 强制刷新回测
- 每个交易日的 Agent trace

主要代码：`src/backtester.py`。

相关提交：

```text
25ba004 回测使用开盘价
d2ba732 增加初始持仓
eb7f1cd 扩展回测功能
9351b0a 增加回测追踪和 LLM 决策日志
```

## 12. 项目配置和运行形态变化

A_Share 新增或使用了以下依赖：

- `akshare`、`baostock`
- `beautifulsoup4`、`playwright`
- `fastapi`、`uvicorn`
- `langgraph`、`google-genai`
- `backoff`

支持的运行方式包括：

- `uv sync`
- Poetry
- 命令行分析
- FastAPI 服务
- 独立回测

主要入口：`src/main.py`、`src/backtester.py`、`backend/main.py`、`run_with_backend.py`。

## 与当前 ai-hedge-fund v2 的差异

当前项目已经转向：

- `hedge_fund/` 包结构
- Fund/Mandate 抽象
- 多 ticker 运行
- 可插拔 Alpha Model
- Textual 终端 UI
- Financial Datasets 数据源
- 统一 LLM provider registry
- 事件研究模块
- 新版 backtesting engine
- `aihf` 命令行入口

A_Share 仍然是：

- `src/` 包结构
- LangGraph workflow
- 单 ticker 分析
- AkShare/BaoStock 数据源
- 中文 Prompt
- FastAPI 后端
- Tavily/Google 新闻检索
- Agent 日志和 API 状态驱动的可观测方式

因此，A_Share 不是当前 v2 的完整超集，而是“旧版架构 + A 股数据 + 新闻/缓存 + Web API”的独立分支。

## 推荐迁移方式

不建议将 A_Share 整个项目直接合并进 `hedge_fund/`。建议建立独立扩展层：

```text
AI_Investment_agent/
├── hedge_fund/              # 原仓库代码，跟随 upstream 更新
├── ashare_extension/        # A 股数据和业务扩展
│   ├── data_adapter.py
│   ├── news.py
│   ├── models.py
│   ├── workflow.py
│   └── cli.py
└── backend_ashare/          # 可选的外部 FastAPI 服务
```

建议按以下顺序迁移：

1. 实现 A 股 `DataClient` 适配器，把 AkShare/BaoStock 数据转换成当前项目接口。
2. 将 Tavily、新闻缓存和 SQLite 缓存放在扩展层。
3. 将宏观分析、多空研究员和辩论室改造成当前项目可调用的 Alpha Model 或分析阶段。
4. 用独立 CLI 启动 A 股流程，例如 `python -m ashare_extension.cli`，不要覆盖 `aihf`。
5. 将 FastAPI 后端放在扩展项目中，通过公共接口调用 `hedge_fund`。

推荐依赖关系：

```text
AkShare/BaoStock/Tavily
          ↓
A 股扩展适配器
          ↓
hedge_fund 的 DataClient / AlphaModel / FundSpec 接口
          ↓
原项目 Pipeline
```

这样同步原仓库时，只需要处理公共接口变化，不需要解决两个完整项目之间的大规模合并冲突。

## 当前分支的维护风险

- 没有发现独立的完整 `tests/` 测试目录。
- 后端默认使用内存日志，重启后数据丢失。
- AkShare、BaoStock、Tavily、Google 搜索等外部服务较多，网络稳定性会影响运行。
- A_Share 与当前 v2 架构差异很大，直接合并会产生大量冲突。
- A_Share 的部分依赖版本较旧，需要单独做 Python 3.12 兼容性验证。

## 依据

本分析依据两个本地仓库的目录、代码和 Git 提交记录整理，不包含任何 API Key，也不构成投资建议。

## 第 1 节迁移验收结果

截至 2026-09-09，第 1 节“A 股数据源适配”已在独立的 `ashare_extension/` 中完成：

- AkShare 财务指标、三大财务报表和新闻已经接入并使用 SQLite 缓存。
- BaoStock 历史 K 线、交易日历和股票基本信息已经接入，支持超时、断线重登和重试。
- 支持沪、深、北证券代码以及中文名称，沪深 300 别名统一映射到 `sh.000300`。
- 股票完整基本信息通过 `AShareDataClient.get_stock_basic()` 暴露。
- 沪深 300 市场级分析通过 `AShareDataClient.get_csi300_analysis()` 暴露。
- 实时行情、资金流、PE/PB/TTM PS 和 52 周区间通过
  `AShareDataClient.get_market_snapshot()` 统一输出。

迁移没有修改 `hedge_fund/` 包。原 A 股项目中由 LLM 根据新闻估算市场数值的逻辑被调整为
真实行情和财务数据，LLM 仅作为可选的文字总结增强，避免生成无法验证的市场数值。

## 第 2 节迁移与风险优化结果

截至 2026-09-09，第 2 节“SQLite 数据缓存层”已保留在独立的
`ashare_extension/` 中。该缓存不会替换 `hedge_fund.data.CachedDataClient`：
SQLite 负责 AkShare/BaoStock 原始数据、TTL 和增量行情，上游 JSON 缓存只负责
`DataClient` 标准返回对象的历史请求。

新增 `ashare_extension/data/cached_client.py`，提供 `CachedAShareDataClient`：

- 历史日期的标准 `DataClient` 请求继续复用上游 JSON 缓存；
- 当日及未来日期请求绕过无 TTL 的 JSON 缓存，由 SQLite TTL 控制新鲜度；
- A 股专用的实时行情、资金流、财务报表、市场快照和沪深 300 分析接口仍可直接调用；
- 全局 `refresh=True` 和单次 `force_refresh=True` 会传递到 SQLite 数据源层。

历史 `get_market_cap(ticker, end_date)` 不再使用当前实时总市值。历史日期在缺少可靠的
历史总股本数据时返回 `None`，避免将当前市值写入历史缓存并形成回测前视偏差。

SQLite 缓存增加同一路径进程内写锁、`busy_timeout`、锁冲突重试、原子写事务和连接统一
关闭。`MARKET_CACHE_SQLITE_TIMEOUT` 可调整数据库锁等待秒数，默认值为 30 秒。

对应测试位于 `ashare_extension/tests/`，覆盖历史/实时两级缓存选择、刷新传播、历史市值
隔离、异构字段 upsert、多实例并发写入和外部数据库写锁恢复。此次优化没有修改
`hedge_fund/` 包。
