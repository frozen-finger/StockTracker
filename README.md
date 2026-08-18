# StockTracker

每周收集全部 A 股中与股权、股东治理相关的公开信息，生成供 ChatGPT 定时任务读取和分析的结构化 JSON。GitHub 侧只负责确定性采集，不调用 GPT、不发送邮件，也不需要保存 OpenAI 或邮箱密钥。

## 监控事件

- 权益变动报告书（含简式、详式）
- 未来 12 个月增持计划
- 提名董事 / 董事候选人
- 临时股东大会 / 临时股东会
- 股东提案 / 临时提案
- 第一大股东或控股股东变更

## 数据源

- 官方公告：巨潮资讯全文检索；权益变动报告书会下载 PDF 并提取少量证据片段，其他公告保留全文检索命中词和标题以控制运行时间。
- 财经新闻：Bing News RSS 聚合搜索，只保留标题、原文链接、摘要证据和发布时间。

数据源彼此隔离。单一来源失败时，报告状态为 `partial`，并在 `warnings` 中记录错误；所有来源均失败且无结果时状态为 `failed`。

## 自动运行

`.github/workflows/weekly-collect.yml` 每周一北京时间 06:00 自动运行，默认采集含当天在内的最近 8 天，避免周界附近漏报。也可以在 Actions 页面手动指定 `days` 和 `end_date`。

Action 会：

1. 安装依赖并运行单元测试。
2. 采集和分类候选信息。
3. 生成 `data/latest.json` 和 `data/history/YYYY-MM-DD.json`。
4. 上传 30 天保留期的 Action Artifact。
5. 在默认分支运行时，把报告提交回 `main`，方便客户端定时任务直接读取。

仓库需要保留 Workflow 的 `contents: write` 权限。如果组织策略把 `GITHUB_TOKEN` 设为只读，请在仓库 **Settings → Actions → General → Workflow permissions** 中允许 Read and write permissions。

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
pytest
stocktracker --days 8 --output-dir data
```

回溯指定日期：

```bash
stocktracker --days 8 --end-date 2026-08-17 --output-dir data
```

## 输出约定

`data/latest.json` 顶层字段包括：

- `schema_version`：当前为 `1`。
- `status`：`complete`、`partial` 或 `failed`。
- `generated_at`：北京时间生成时间。
- `window_start` / `window_end`：采集窗口。
- `stats`：来源和事件数量。
- `warnings`：来源失败信息。
- `documents`：去重后的候选公告与新闻。

每条 document 包含稳定 ID、来源类型、公司与股票代码（来源可提供时）、发布时间、原文链接、命中的事件、关键词、少量证据片段及正文提取状态。它是“待 GPT 研判的候选集合”，本地关键词命中不等于投资事实已经成立。

## 客户端定时任务建议

把 ChatGPT 定时任务设置在每周一 07:00 或更晚，读取仓库默认分支的 `data/latest.json`。任务应先检查：

1. `generated_at` 是否为本周且 `window_end` 是否符合预期。
2. `status` 与 `warnings` 是否显示采集异常。
3. 对 documents 合并同公司、同事件的公告与新闻，区分正式公告、媒体转述和仅关键词提及。
4. 输出六类事件、关键主体、持股变化、未来计划、潜在影响、风险和置信度，并附原文链接。

仓库公开时，请勿在报告、Workflow 或代码中写入邮箱地址、访问令牌或其他密钥。
