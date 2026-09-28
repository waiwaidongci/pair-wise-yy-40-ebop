# 建筑抗震鉴定与加固排序

依据结构、用途、人员密度和历史缺陷生成鉴定与加固优先级。

## 模块结构

- `app.py`：参数解析、依赖组装和HTTP服务启动。
- `src/domain.py`：数据结构、错误、状态和基础校验。
- `src/rules.py`：状态机、角色矩阵、优先级、期限和关闭不变量。
- `src/repository.py`：SQLite建表、事务、版本控制和审计链。
- `src/service.py`：权限检查、用例编排、并发控制和审计。
- `src/http_api.py`：JSON路由和统一错误响应。
- `src/audit.py`：UTC时间和SHA-256审计事件。
- `static/index.html`：最小演示页。
- `tests/`：完整流程、规则和失败测试。

## 初始化与启动

```bash
python3 app.py --db ./data.db --port 8317
```

默认端口为`8317`，首次启动自动建库。使用`X-Actor`和`X-Role`请求头传递身份。

## 主要接口

- `GET /health`
- `GET /api/items`
- `POST /api/items`
- `GET /api/items/{id}`
- `POST /api/items/{id}/records`（复核事项一律以待办`open`建立，不允许创建即关闭）
- `GET /api/items/{id}/records?status=open|closed`
- `GET /api/items/{id}/records/{record_id}`（含历次处置记录）
- `POST /api/items/{id}/records/{record_id}/dispose`，提交`{"action":"close|reopen","note":"..."}`
- `POST /api/items/{id}/transition`，必须提交`expected_version`
- `GET /api/audit`

允许角色：assessor, structural_engineer, review_board, viewer。风险分值和人员密度共同影响排序；审核通过前必须完成评估、设计和施工证据登记。

### 事项处置

- 评估员（assessor）或结构工程师（structural_engineer）按事项编号提交`action=close`的处理说明（`note`必填）后事项关闭。
- 审核委员会（review_board）发现处置失实时可`action=reopen`重开，重开原因（`note`）必填；评估员/工程师不能重开，委员会不能直接关闭。
- 已关闭事项不能重复关闭、待办事项不能重复重开；每次处置都在同一事务内追加处置历史、推进项目`version`。
- 使用旧`expected_version`提交任何状态迁移都会返回409冲突；项目仍有待办事项时，验收（转换到`accepted`）返回409并提示待办数量。只有关闭最后一个待办后才能继续验收。
- 项目与事项响应中包含`open_record_count`、`acceptance_blocked`、`item_version`等字段，页面可据此提交处置并列出仍挡住验收的事项。

## 测试

```bash
python3 -m unittest discover -s tests -v
```
