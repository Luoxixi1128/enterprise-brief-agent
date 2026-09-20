# 企业需求拆解 Agent · V5.0 公开部署版

将企业原始需求整理为八节任务书。支持自然语言修改、待确认事项同步、逐节手动编辑，人工审阅后生成 Word 任务书与 Excel 输入样例表。

本目录是从 V5.0 提取的独立部署源码，包含前端、Python 后端、Agent 提示词、结构校验和文件生成脚本。**目前完成的是部署准备和本地验证，尚未发布线上网址。** 不包含真实客户材料、本机任务数据库、API 密钥或旧版本备份。

## 使用流程

1. 新建任务，上传需求文档或填写说明。
2. Agent 判断要生成、修改、记录确认还是提问；生成后检查并尝试修正。
3. 在同一补充框提出后续要求，或手动编辑任务书、填写待确认事项。
4. 审阅并确认当前稿，下载文件。

模型由服务器统一提供，访客无需配置密钥。第08节选择的是业务任务的输出要求，例如单文件 HTML；本产品导出的任务书仍为 Word，缺少样例时同时生成 Excel 输入样例表。

## 免费部署

使用 **Render Free Python Web Service + Supabase Free 数据库和私有文件存储**，配置见 [DEPLOY.md](DEPLOY.md)。不申请付费磁盘，也不使用会到期的 Render Free PostgreSQL。

Render 只负责运行网站，本地目录是可丢弃的缓存。任务、确认答案、历史版本、处理进度和调用计数保存在 Supabase PostgreSQL；上传材料与导出文件保存在私有 bucket。云端保存失败会报错，不降级成只保存本地。

免费平台有休眠和用量限制，适用于小规模公测。Render 休眠后的首次访问需要等待唤醒；Supabase 长期闲置可能暂停，需要恢复后继续使用。详见 [Render 免费服务说明](https://render.com/docs/free) 和 [Supabase 免费额度](https://supabase.com/pricing)。平台限制不等同于永久在线保证。

生产启动：

```sh
pip install -r requirements.txt
gunicorn -c gunicorn.conf.py wsgi:app
```

部署前执行 [supabase/schema.sql](supabase/schema.sql)。必填环境变量为 `SUPABASE_URL`、`SUPABASE_SECRET_KEY`、`PUBLIC_STORAGE_BACKEND=supabase`、`BRIEF_API_BASE_URL`、`BRIEF_MODEL`、`BRIEF_API_KEY`、`PUBLIC_SESSION_SECRET`。Render 自动提供公网域名；自定义域名另设 `PUBLIC_ORIGIN`。`.env.example` 仅为字段参考，服务从环境变量读取配置。

`SUPABASE_SECRET_KEY` 使用后台 `sb_secret_` 密钥；数据库与公司模型密钥均只进入服务器的秘密环境变量。模型接口须兼容 OpenAI Chat Completions。

## 公测边界

- 每个浏览器通过签名、HttpOnly、Secure、SameSite Cookie 使用独立工作区。任务查询、修改和下载均限定在该工作区。
- 当前没有账户登录或跨设备恢复。连续90天未打开首页、清除 Cookie 或更换浏览器后，无法访问原工作区。
- 不展示本机真实案例，不开放访客修改模型配置。上传材料可查看提取文本、下载原文件；历史任务书可下载。
- 每工作区20个任务；每任务8份材料、单文件4MB、40条补充说明、80个历史版本、30次文件交付。已删除任务仍计入容量。
- 默认每工作区每日24次模型请求、全站160次，UTC 日期重置，失败请求也计数。最多同时处理2个任务。一次生成需要多次调用；这是请求次数限制，不是精确费用上限。
- 最多200个匿名工作区，每小时最多新建30个。文件上限每工作区50MB、全站700MB；任务及版本 JSON 正文上限每工作区25MB、全站200MB，数据库实际空间还包含索引等开销。上传失败的预留空间也计入文件上限。
- 单实例运行，数据库租约防止更新部署时两个实例同时写入。更新期间可能暂时不能操作；中断任务可从已保存步骤继续，已发出的模型请求不能保证不重复计费。

材料保存在托管平台，并在处理时发送给网站配置的模型服务。运营者可维护数据；工作区隔离不等于端到端加密。“删除任务”为可恢复删除，当前没有永久删除入口、自动清理、跨设备找回或多实例队列。重要结果请下载留存。

## 开发与验证

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest -v test_public
npm ci --prefix tests_cloud
.venv/bin/python -m unittest -v test_cloud
```

云存储测试需要 Node.js；可用 `NODE_BINARY` 指定其路径。测试在回环地址启动临时 REST 服务，用 PGlite 执行真实 SQL，文件存储和模型使用替身，不连接任何真实云项目，不消耗模型额度。测试不等于线上 Supabase/Render 验收。详见 [VERIFICATION.md](VERIFICATION.md)。

仅本地开发时可使用 `PUBLIC_STORAGE_BACKEND=local`，配合单独的持久目录。Render 免费实例必须使用 `supabase`。

## 项目结构

| 路径 | 作用 |
| --- | --- |
| `web/` | 四步交互页面 |
| `agent_runtime.py` | 下一步决策、生成、检查、修正和恢复 |
| `confirmation_actions.py` | 按用户明确要求同步确认事项与格式选择 |
| `core.py` | 任务、版本、材料解析和导出 |
| `model.py`、`prompts/` | 模型接入与提示词 |
| `public_runtime.py`、`public_server.py` | 访客隔离、公共 API 与限额 |
| `cloud_storage.py`、`supabase/schema.sql` | 云端保存、私有文件、配额与部署租约 |
| `vendor/` | 固定版本的结构规范、校验与文件生成脚本 |
| `render.yaml`、`Dockerfile` | 部署配置 |
| `test_public.py`、`test_cloud.py`、`tests_cloud/` | 本地回归验证 |
| `docs/releases/` | V1.0—V5.0 产品迭代 |
| `source-baseline.json` | 提取本机 V5.0 时的源码哈希 |

本仓库尚未附开源许可证；公开可见不等于已授予任意再分发或商业使用许可。项目负责人选定许可证后再补充。
