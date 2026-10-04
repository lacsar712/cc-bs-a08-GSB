import os
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext
from sanic import Sanic
from sanic.response import json as sanic_json

from db import (
    READING_COLUMNS,
    create_pool,
    ensure_schema,
    serialize_log,
    serialize_reading,
    seed_if_empty,
)
from rules import ConversionError, resolve_submission

SECRET = os.environ.get("JWT_SECRET", "bridge-strain-dev-secret")
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

USERS = {
    "surveyor": {"role": "writer", "password_hash": pwd.hash("surv123456")},
    "reviewer": {"role": "reader", "password_hash": pwd.hash("rev123456")},
}

app = Sanic("bridge-strain-shift")


def _auth_header(request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


def _decode_user(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None
    sub = payload.get("sub")
    if sub not in USERS:
        return None
    return {"username": sub, "role": payload.get("role")}


def _require_user(request) -> dict:
    return _decode_user(_auth_header(request))


def _iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat()


@app.before_server_start
async def setup(_app, _loop):
    pool = await create_pool()
    _app.ctx.pool = pool
    await ensure_schema(pool)
    await seed_if_empty(pool)


@app.after_server_stop
async def teardown(_app, _loop):
    pool = _app.ctx.pool
    if pool:
        await pool.close()


@app.get("/api/health")
async def health(_request):
    return sanic_json({"status": "ok", "service": "bridge-strain-shift"})


@app.post("/api/auth/login")
async def login(request):
    body = request.json or {}
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    user = USERS.get(username)
    if not user or not pwd.verify(password, user["password_hash"]):
        return sanic_json({"detail": "用户名或密码错误"}, status=401)
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode(
        {"sub": username, "role": user["role"], "exp": exp},
        SECRET,
        algorithm="HS256",
    )
    return sanic_json(
        {"access_token": token, "username": username, "role": user["role"]}
    )


def _reading_payload(row, message: str | None = None) -> dict:
    payload = {
        **serialize_reading(row),
        "created_at": _iso(row["created_at"]),
        "processed_at": _iso(row["processed_at"]),
    }
    if message:
        payload["message"] = message
    return payload


@app.get("/api/readings")
async def list_readings(request):
    if not _require_user(request):
        return sanic_json({"detail": "未登录"}, status=401)
    pool = request.app.ctx.pool
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT {READING_COLUMNS}
                FROM strain_readings
                ORDER BY id DESC
                """
            )
            rows = await cur.fetchall()
    return sanic_json([_reading_payload(r) for r in rows])


@app.post("/api/readings")
async def create_reading(request):
    user = _require_user(request)
    if not user:
        return sanic_json({"detail": "未登录"}, status=401)
    if user["role"] != "writer":
        return sanic_json({"detail": "仅测量员可提交应变读数"}, status=403)

    # 双路径（直填微应变 / 原始电压换算）共用同一解析入口，
    # 非法灵敏度、换算出界等失败在此统一退回，措辞与前端表单逐字一致。
    try:
        data = resolve_submission(request.json or {})
    except ConversionError as exc:
        return sanic_json({"detail": str(exc)}, status=400)

    pool = request.app.ctx.pool
    async with pool.connection() as conn:
        try:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        INSERT INTO strain_readings
                            (span_code, microstrain, raw_voltage, sensitivity,
                             rated_voltage, status, created_by, created_at)
                        VALUES (%s, %s, %s, %s, %s, 'pending', %s, now())
                        RETURNING """ + READING_COLUMNS,
                        (
                            data["span_code"],
                            data["microstrain"],
                            data["raw_voltage"],
                            data["sensitivity"],
                            data["rated_voltage"],
                            user["username"],
                        ),
                    )
                    row = await cur.fetchone()
                    # 入队与换算流水同一事务：要么同时可见，要么同时回滚。
                    await cur.execute(
                        """
                        INSERT INTO conversion_logs
                            (reading_id, span_code, path, raw_voltage,
                             sensitivity, rated_voltage, microstrain,
                             created_by, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                        """,
                        (
                            row["id"],
                            row["span_code"],
                            "voltage" if data["converted_from_voltage"] else "direct",
                            row["raw_voltage"],
                            row["sensitivity"],
                            row["rated_voltage"],
                            row["microstrain"],
                            user["username"],
                        ),
                    )
        except Exception:
            await conn.rollback()
            raise

    return sanic_json(
        _reading_payload(row, "已入队，后台工人将认领并判定"),
        status=201,
    )


@app.get("/api/conversion-logs")
async def list_conversion_logs(request):
    # 复核员与测量员均可查看换算流水；接口只读，参数不可在此修改。
    if not _require_user(request):
        return sanic_json({"detail": "未登录"}, status=401)
    pool = request.app.ctx.pool
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, reading_id, span_code, path, raw_voltage,
                       sensitivity, rated_voltage, microstrain,
                       created_by, created_at
                FROM conversion_logs
                ORDER BY id DESC
                LIMIT 200
                """
            )
            rows = await cur.fetchall()
    out = []
    for r in rows:
        item = serialize_log(r)
        item["created_at"] = _iso(r["created_at"])
        out.append(item)
    return sanic_json(out)
