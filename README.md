# Story-Patch (CanonGuard)

CanonGuard 是一个叙事一致性(Narrative Canon)研究与原型系统:把剧本/小说拆解为 PlotUnit 与场景级事实,
在临时知识图谱上审计设定冲突,并为写作者的"卡文点"提供可回放的续写建议。

本仓库只包含核心代码;设计文档、实验记录与第三方语料保留在本地,不随仓库分发。

## 目录结构

```
apps/api          FastAPI 后端 (Python 3.12, uv)
  canonguard/     core / corpus / plot / harness / runs / api / eval / llm / db
  alembic/        数据库迁移
  tests/          pytest 用例与合成 fixtures
apps/web          Next.js 前端 (pnpm workspace)
packages/contracts OpenAPI 契约与由 openapi.json 生成的类型
infra/            docker-compose (Postgres / Neo4j / MinIO / Valkey) + Neo4j 约束
docs/             方法对齐说明
```

## 环境准备

```bash
cp .env.example .env      # 填入 LLM provider 的模型名与 key
make setup                # uv sync + pnpm install
make up                   # 启动 infra (宿主机端口 5433/7688 避让本地实例)
make init                 # alembic upgrade head + MinIO bucket 初始化
```

## 运行

```bash
make api                  # 127.0.0.1:8100
make web                  # localhost:3000
```

## 校验

```bash
make test                 # pytest
make check                # ruff / mypy / typecheck / lint
make contracts            # 重新导出 openapi.json 并生成前端类型
```

CI (`.github/workflows/ci.yml`) 会跑同一套检查,并强制 `openapi.json` 与生成的类型不产生漂移。

## 数据与授权说明

- `data/` 下的来源文本、抽取结果与索引均被 `.gitignore` 排除,仓库中只保留 `.gitkeep`。
- 测试用的 `apps/api/tests/fixtures/` 是为对齐数据格式而手写的合成样例,不含任何第三方语料原文。
- 研究里用到的 STAGE 数据集未附带许可证(仅限科研用途)、DramaBench 为 MIT;两者都不通过本仓库分发,
  请按各自条款自行获取。

## 许可

本项目目前为研究原型,未附带开源许可证;在明确授权前不授予任何使用许可。
