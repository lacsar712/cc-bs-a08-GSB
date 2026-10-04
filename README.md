# 桥梁应变班交台

测量员上报跨段编号与读数：**原始电压须先换算成微应变**再判定。换算专页设置灵敏度系数 K 与额定（激励）电压 E，报送支持「原始电压由服务端换算」与「直填微应变」两条路径，结果一致。后台工人用 `FOR UPDATE SKIP LOCKED` 认领待处理队列，按 **80～220 με** 判定 **合格** 或 **越界**。

## 换算公式

```
ε(με) = U(mV) ÷ (K × E(V)) × 1000
```

默认 K=2.0、E=5.0 V：U=1.5 mV → 150 με（合格）。微应变量程 0～100000 με，超出或灵敏度非法时，页面试算与直打接口以**同一句措辞**退回；读数入队与换算流水在**同一数据库事务**落库，任一失败整体回滚。

顶栏「换算专页」含：参数区（K/E，测量员可改、复核员只读）、双路径报送（输入即服务端试算，不入队）、换算流水（含 K/E/公式，复核员可见不可改）。

| 接口 | 说明 |
|------|------|
| `GET /api/settings` | 查看 K/E（两种角色均可） |
| `PUT /api/settings` | 修改 K/E（仅测量员） |
| `POST /api/convert/preview` | 试算换算与判定，不入队 |
| `GET /api/conversions` | 换算流水 |
| `POST /api/readings` | 报送：`raw_voltage` 或 `microstrain` 二选一 |

## 技术栈

| 层 | 选型 |
|----|------|
| 接口 | Python Sanic + psycopg（异步连接池） |
| 工人 | `worker.py`（psycopg 同步，`FOR UPDATE SKIP LOCKED`） |
| 页面 | Mithril.js + Vite，nginx 反代 `/api` |
| 数据库 | PostgreSQL 16 |

## 端口

| 服务 | 地址 |
|------|------|
| 页面 | http://localhost:3198 |
| 接口 | http://localhost:8198 |
| PostgreSQL | localhost:54398（库名 `bridgestrain`） |

## 账号

| 用户 | 密码 | 权限 |
|------|------|------|
| surveyor | surv123456 | 测量员，可提交读数 |
| reviewer | rev123456 | 复核员，只读列表 |

## 启动

```bash
cd projects/19-bridge-strain-shift
docker compose up --build
```

健康检查：`GET http://localhost:8198/api/health` → `{"status":"ok","service":"bridge-strain-shift"}`

## 种子数据

| 跨段 | 微应变 | 结论 |
|------|--------|------|
| 跨中S1 | 150 με | 合格 |
| 支座S2 | 40 με | 越界 |

## 本地开发（可选）

```bash
cd backend && pip install -r requirements.txt
python -m sanic api.app --host=0.0.0.0 --port=8000 --single-process
python worker.py
cd frontend && npm install && npm run dev
```

接口进程默认监听容器内 **8000**，对外映射 **8198**。
