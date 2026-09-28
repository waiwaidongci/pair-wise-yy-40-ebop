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
- `POST /api/items/{id}/records`
- `GET /api/items/{id}/records?status=open|closed`
- `GET /api/items/{id}/blocking`，列出仍挡住验收的待办事项
- `POST /api/items/{id}/transition`，必须提交`expected_version`
- `POST /api/records/{id}/dispositions`，提交事项处置（见下）
- `GET /api/records/{id}/dispositions`，处置历史
- `GET /api/audit`

允许角色：assessor, structural_engineer, review_board, viewer。风险分值和人员密度共同影响排序；审核通过前必须完成评估、设计和施工证据登记。

## 复核事项处置

复核阶段提出的事项（records）创建后可反复处置，不能一次写成已关闭了事：

- `POST /api/records/{id}/dispositions`，请求体：`{"action":"close","note":"处理说明","expected_version":N}`。
  - `action=close`：assessor或structural_engineer提交处理说明并关闭事项。
  - `action=reopen`：仅review_board可操作，`note`为重开原因，必填。
- 每次处置都会把项目版本`version+1`（与处置在同一事务内完成）；仍拿旧`expected_version`提交验收会返回409冲突。
- 每个待办事项都关闭（`open_record_count=0`）后，项目才能转换到`accepted`；否则返回409并提示未关闭数量。
- 项目详情包含`open_record_count`与`acceptance_blocked`字段，便于页面判断复核结论是否仍然有效。

## 测试

```bash
python3 -m unittest discover -s tests -v
```
