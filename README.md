# ACLG 声学巡检记录验收服务

声学巡检仪以二进制格式交接巡检记录，传输截断可能让后续分析误读"貌似完整"的数据。
本服务提供纯后端上传接口：接收工程师上传整份记录，服务在请求内**同步解析**并给出判定——
整份**放行（PASS）**，或报告**首个结构错误**（含损坏数据块的零基索引）。

- 纯后端：无数据库、无 worker，单文件 multipart/form-data 上传
- 上传上限 **8 MiB**，超限返回 `413`
- 只返回首个错误，绝不返回部分成功或固定诊断结果

## 二进制记录格式（小端序）

头部固定 7 字节：

| 偏移 | 字段 | 字节数 | 类型 | 说明 |
|---|---|---|---|---|
| 0 | 魔数 | 4 | ASCII | 固定为 `ACLG` |
| 4 | 版本 | 1 | uint8 | 固定为 `1` |
| 5 | 块数 | 2 | uint16 LE | 声明的数据块数量 |

其后紧跟声明数量的数据块，每块结构：

| 字段 | 字节数 | 类型 | 说明 |
|---|---|---|---|
| 样本数 N | 2 | uint16 LE | 本块样本个数 |
| 样本 | 2 × N | int16 LE | 恰好 N 个有符号 16 位样本 |

## 判定规则（只返回首个错误）

| 情形 | 结果 |
|---|---|
| 魔数错误、版本不符或头部不足 7 字节 | `HEADER_INVALID` |
| 某块缺少样本数或样本数据 | `TRUNCATED_BLOCK`，携带该块零基索引 `block_index` |
| 声明块全部解析完后仍有剩余字节 | `TRAILING_BYTES` |
| 全部合法 | `PASS`，返回声明块数与样本总数 |

## API

### `POST /inspect`

`multipart/form-data`，文件字段名 `file`。可选查询参数 `include_block_stats=true`
在放行响应中附加逐块样本摘要（无法解析为布尔值时返回 `422` 参数错误）。

- 合法记录 → `200 OK`：

  ```json
  {"status": "PASS", "block_count": 2, "total_samples": 5}
  ```

- 合法记录且 `?include_block_stats=true` → `200 OK`，按文件顺序附加
  `block_stats`（零基索引、样本数、最小值、最大值；空块的最小/最大值为 `null`）：

  ```json
  {"status": "PASS", "block_count": 2, "total_samples": 5,
   "block_stats": [
     {"index": 0, "sample_count": 3, "min": -2, "max": 3},
     {"index": 1, "sample_count": 2, "min": -100, "max": 100}
   ]}
  ```

- 结构非法 → `422 Unprocessable Content`（统计随校验同一次遍历完成，
  一旦报错即整份判 FAIL，绝不返回部分块的摘要）：

  ```json
  {"status": "FAIL", "error": {"code": "TRUNCATED_BLOCK", "message": "block 1: ...", "block_index": 1}}
  ```

- 超过 8 MiB → `413 Payload Too Large`

### `GET /health`

返回 `{"status": "ok"}`，供 Compose 健康检查与人工探活。

## 启动（Docker Compose）

```bash
docker compose up --build -d api                  # 默认映射宿主 8000 端口
API_PORT=9000 docker compose up --build -d api    # 用 API_PORT 覆盖宿主端口
```

## 上传示例

生成一份合法样例并上传：

```bash
python3 - <<'PY'
import struct
rec  = b"ACLG" + bytes([1]) + struct.pack("<H", 2)      # 头部：2 个块
rec += struct.pack("<H", 3) + struct.pack("<3h", 1, -2, 3)
rec += struct.pack("<H", 2) + struct.pack("<2h", 100, -100)
open("sample.aclg", "wb").write(rec)
PY

curl -s -F "file=@sample.aclg" http://localhost:8000/inspect
# {"status":"PASS","block_count":2,"total_samples":5}
```

## 验收（一次性 verify 服务）

```bash
docker compose up --build --exit-code-from verify
docker compose down
```

`verify` 等待 `api` 健康后，通过真实 HTTP 对运行中的服务执行验收：
合法/空记录放行、坏魔数、坏版本、头部不全、块截断（校验零基索引）、
尾随字节、首错误优先、8 MiB 边界与超限 413。全部通过时退出码为 0，
`--exit-code-from verify` 会把该退出码作为整条命令的结果。

## 本地开发

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload   # 本地起服务
pytest                          # 单元测试（解析器 + API 契约，TestClient）
pytest verify/                  # 验收测试（需服务已运行，可用 API_BASE_URL 指向）
```

## 项目结构

```
app/
  main.py       FastAPI 路由、8 MiB 限制、错误到响应的映射
  parser.py     ACLG 二进制解析，遇首个错误即抛 RecordError
  schemas.py    Pydantic 响应模型（PASS / FAIL）
tests/          单元测试（pytest + TestClient）
verify/         验收测试（对运行中的服务发真实 HTTP）
Dockerfile      python:3.12-slim 镜像
docker-compose.yml  api 服务 + 一次性 verify 服务
```
