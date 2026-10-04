# 桥梁应变班交台

测量员上报跨段编号与读数：可**直接填写微应变**，也可在**换算专页**设置应变片
**灵敏度 K** 与**额定电压 U额**后填写**原始电压**，由服务端换算成微应变写入单据。
后台工人用 `FOR UPDATE SKIP LOCKED` 认领待处理队列，按 **80～220 με** 判定
**合格** 或 **越界**。两条报送路径共用同一服务端换算与校验，结果与退回措辞完全一致。

## 换算公式

```
微应变 με = 原始电压 U ÷ (额定电压 U额 × 灵敏度 K) × 1_000_000
```

| 参数 | 合法范围 |
|------|----------|
| 灵敏度 K | 0.1～10（数字） |
| 额定电压 U额 | 0.1～1000 V |
| 换算微应变 | −100000～100000 με，超出即「换算出界」退回，不入队 |

- 原始电压与微应变二选一，同时填写退回。
- 灵敏度非法、额定电压非法、换算出界等情况，前端表单与直接调用接口
  返回同一 `400 {"detail": ...}` 措辞。
- 读数入队与换算流水在**同一数据库事务**提交；失败则两者都不落库。
- 复核员可在换算专页查看参数与换算流水，但参数只读、不能报送。

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

换算与校验的单元测试（无需数据库）：

```bash
cd backend && python -m unittest test_rules -v
```

接口进程默认监听容器内 **8000**，对外映射 **8198**。

## 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 登录获取 JWT |
| GET | `/api/readings` | 读数列表（含原始电压、灵敏度、额定电压） |
| POST | `/api/readings` | 报送：`microstrain` 直填，或 `voltage`+`sensitivity`+`rated_voltage` 换算 |
| GET | `/api/conversion-logs` | 换算流水（测量员/复核员均可查，只读） |

报送示例（原始电压路径，K=2、U额=5V 时 0.0015 V 换算为 150 με）：

```bash
curl -X POST http://localhost:8198/api/readings \
  -H "Authorization: Bearer <token>" -H 'Content-Type: application/json' \
  -d '{"span_code":"跨中S3","voltage":0.0015,"sensitivity":2.0,"rated_voltage":5.0}'
```
