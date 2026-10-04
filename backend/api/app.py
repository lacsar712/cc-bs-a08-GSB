import os
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext
from sanic import Sanic
from sanic.response import json as sanic_json

from db import (
    READING_COLUMNS,
    SETTINGS_SELECT,
    create_pool,
    ensure_schema,
    seed_if_empty,
)
from rules import (
    ERR_PATH_AMBIGUOUS,
    ERR_PATH_MISSING,
    ConversionError,
    conversion_formula_text,
    convert_voltage_to_microstrain,
    ensure_microstrain_range,
    judge_microstrain,
    parse_microstrain,
    parse_rated_voltage,
    parse_raw_voltage,
    parse_sensitivity,
)

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


def _require_user(request) -> dict | None:
    return _decode_user(_auth_header(request))


def _iso(dt) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _err(message: str, status: int = 400):
    # 统一退回信封：表单与直打均读 detail 文案
    return sanic_json({"detail": message}, status=status)


def _reading_payload(row) -> dict:
    return {
        "id": row["id"],
        "span_code": row["span_code"],
        "microstrain": row["microstrain"],
        "raw_voltage": row.get("raw_voltage"),
        "sensitivity": row.get("sensitivity"),
        "rated_voltage": row.get("rated_voltage"),
        "input_mode": row.get("input_mode"),
        "verdict": row["verdict"],
        "reason": row["reason"],
        "status": row["status"],
        "created_by": row["created_by"],
        "created_at": _iso(row["created_at"]),
        "processed_at": _iso(row["processed_at"]),
    }


async def _load_settings(cur) -> dict:
    await cur.execute(SETTINGS_SELECT)
    return await cur.fetchone()


def _provided(body: dict, key: str) -> bool:
    return key in body and body[key] is not None and body[key] != ""


async def _resolve_input(cur, body: dict) -> dict:
    """把双路径输入统一解析成 microstrain；所有退回措辞由 rules 产出。

    电压路径未自带 K/E 时回落到换算专页已保存参数；直填路径不做换算，
    只校验量程。两条路径产出同一字段集，后续入队逻辑无分叉。
    """
    has_voltage = _provided(body, "raw_voltage")
    has_microstrain = _provided(body, "microstrain")
    if has_voltage and has_microstrain:
        raise ConversionError(ERR_PATH_AMBIGUOUS)
    if not has_voltage and not has_microstrain:
        raise ConversionError(ERR_PATH_MISSING)

    if has_voltage:
        sensitivity = (
            parse_sensitivity(body["sensitivity"])
            if _provided(body, "sensitivity")
            else None
        )
        rated_voltage = (
            parse_rated_voltage(body["rated_voltage"])
            if _provided(body, "rated_voltage")
            else None
        )
        if sensitivity is None or rated_voltage is None:
            settings = await _load_settings(cur)
            if sensitivity is None:
                sensitivity = float(settings["sensitivity"])
            if rated_voltage is None:
                rated_voltage = float(settings["rated_voltage"])
        raw_voltage = parse_raw_voltage(body["raw_voltage"])
        microstrain = convert_voltage_to_microstrain(
            raw_voltage, sensitivity, rated_voltage
        )
        return {
            "input_mode": "voltage",
            "raw_voltage": raw_voltage,
            "sensitivity": sensitivity,
            "rated_voltage": rated_voltage,
            "microstrain": microstrain,
            "formula": conversion_formula_text(
                raw_voltage, sensitivity, rated_voltage, microstrain
            ),
        }

    microstrain = ensure_microstrain_range(parse_microstrain(body["microstrain"]))
    return {
        "input_mode": "direct",
        "raw_voltage": None,
        "sensitivity": None,
        "rated_voltage": None,
        "microstrain": microstrain,
        "formula": f"直填微应变：{microstrain:g} με",
    }


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
        return _err("用户名或密码错误", status=401)
    exp = datetime.now(timezone.utc) + timedelta(hours=8)
    token = jwt.encode(
        {"sub": username, "role": user["role"], "exp": exp},
        SECRET,
        algorithm="HS256",
    )
    return sanic_json(
        {"access_token": token, "username": username, "role": user["role"]}
    )


@app.get("/api/settings")
async def get_settings(request):
    """复核员也可查看灵敏度与额定电压，但不能修改。"""
    if not _require_user(request):
        return _err("未登录", status=401)
    pool = request.app.ctx.pool
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            row = await _load_settings(cur)
    return sanic_json(
        {
            "sensitivity": row["sensitivity"],
            "rated_voltage": row["rated_voltage"],
            "updated_by": row["updated_by"],
            "updated_at": _iso(row["updated_at"]),
        }
    )


@app.put("/api/settings")
async def update_settings(request):
    user = _require_user(request)
    if not user:
        return _err("未登录", status=401)
    if user["role"] != "writer":
        return _err("仅测量员可修改换算参数", status=403)
    body = request.json or {}
    try:
        # 与报送、试算同一组解析函数，非法时退回同一句措辞
        sensitivity = parse_sensitivity(body.get("sensitivity"))
        rated_voltage = parse_rated_voltage(body.get("rated_voltage"))
    except ConversionError as exc:
        return _err(str(exc))

    pool = request.app.ctx.pool
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO conversion_settings (id, sensitivity, rated_voltage,
                                                 updated_by, updated_at)
                VALUES (1, %s, %s, %s, now())
                ON CONFLICT (id) DO UPDATE
                SET sensitivity = EXCLUDED.sensitivity,
                    rated_voltage = EXCLUDED.rated_voltage,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = now()
                RETURNING sensitivity, rated_voltage, updated_by, updated_at
                """,
                (sensitivity, rated_voltage, user["username"]),
            )
            row = await cur.fetchone()
        await conn.commit()
    return sanic_json(
        {
            "sensitivity": row["sensitivity"],
            "rated_voltage": row["rated_voltage"],
            "updated_by": row["updated_by"],
            "updated_at": _iso(row["updated_at"]),
            "message": "换算参数已保存",
        }
    )


@app.post("/api/convert/preview")
async def convert_preview(request):
    """只试算不入队：页面双路径输入实时预览，失败时退回与报送完全一致的措辞。"""
    if not _require_user(request):
        return _err("未登录", status=401)
    body = request.json or {}
    pool = request.app.ctx.pool
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                resolved = await _resolve_input(cur, body)
    except ConversionError as exc:
        return _err(str(exc))
    verdict, reason = judge_microstrain(resolved["microstrain"])
    return sanic_json({**resolved, "verdict": verdict, "reason": reason})


@app.get("/api/conversions")
async def list_conversions(request):
    """换算流水：复核员可见，含灵敏度/额定电压/公式。"""
    if not _require_user(request):
        return _err("未登录", status=401)
    pool = request.app.ctx.pool
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, reading_id, span_code, input_mode, raw_voltage,
                       sensitivity, rated_voltage, microstrain, formula,
                       created_by, created_at
                FROM conversion_logs
                ORDER BY id DESC
                """
            )
            rows = await cur.fetchall()
    return sanic_json(
        [
            {
                "id": r["id"],
                "reading_id": r["reading_id"],
                "span_code": r["span_code"],
                "input_mode": r["input_mode"],
                "raw_voltage": r["raw_voltage"],
                "sensitivity": r["sensitivity"],
                "rated_voltage": r["rated_voltage"],
                "microstrain": r["microstrain"],
                "formula": r["formula"],
                "created_by": r["created_by"],
                "created_at": _iso(r["created_at"]),
            }
            for r in rows
        ]
    )


@app.get("/api/readings")
async def list_readings(request):
    if not _require_user(request):
        return _err("未登录", status=401)
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
        return _err("未登录", status=401)
    if user["role"] != "writer":
        return _err("仅测量员可提交应变读数", status=403)
    body = request.json or {}
    span_code = str(body.get("span_code", "")).strip()
    if not span_code:
        return _err("跨段编号不能为空")

    pool = request.app.ctx.pool
    async with pool.connection() as conn:
        try:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    # 换算（非法灵敏度/出界在此抛出，整笔回滚，不留任何记录）
                    resolved = await _resolve_input(cur, body)
                    await cur.execute(
                        """
                        INSERT INTO strain_readings
                            (span_code, microstrain, raw_voltage, sensitivity,
                             rated_voltage, input_mode, status, created_by, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s, now())
                        RETURNING id
                        """,
                        (
                            span_code,
                            resolved["microstrain"],
                            resolved["raw_voltage"],
                            resolved["sensitivity"],
                            resolved["rated_voltage"],
                            resolved["input_mode"],
                            user["username"],
                        ),
                    )
                    reading_row = await cur.fetchone()
                    reading_id = reading_row["id"]
                    # 换算流水与入队同一次落库：同一事务，任一失败一起回滚
                    await cur.execute(
                        """
                        INSERT INTO conversion_logs
                            (reading_id, span_code, input_mode, raw_voltage,
                             sensitivity, rated_voltage, microstrain, formula,
                             created_by, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                        RETURNING id
                        """,
                        (
                            reading_id,
                            span_code,
                            resolved["input_mode"],
                            resolved["raw_voltage"],
                            resolved["sensitivity"],
                            resolved["rated_voltage"],
                            resolved["microstrain"],
                            resolved["formula"],
                            user["username"],
                        ),
                    )
                    log_row = await cur.fetchone()
                    await cur.execute(
                        "UPDATE strain_readings SET conversion_log_id = %s WHERE id = %s",
                        (log_row["id"], reading_id),
                    )
        except ConversionError as exc:
            return _err(str(exc))

        async with conn.cursor() as cur:
            await cur.execute(
                f"SELECT {READING_COLUMNS} FROM strain_readings WHERE id = %s",
                (reading_id,),
            )
            row = await cur.fetchone()

    payload = _reading_payload(row)
    payload["message"] = "已入队，后台工人将认领并判定"
    return sanic_json(payload, status=201)
