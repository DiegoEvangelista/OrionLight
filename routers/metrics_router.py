"""
Orion Light - Metrics Router
Fornece endpoints de analise de consumo por periodo para o dashboard e relatorios.
"""
import csv
import io
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import RequestLog, User, get_db
from routers.auth_router import require_admin

router = APIRouter(prefix="/v1/metrics", tags=["metrics"])


# helpers
def _parse_period(period, from_dt, to_dt):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now
    if period == "yesterday":
        y = now - timedelta(days=1)
        return y.replace(hour=0, minute=0, second=0, microsecond=0), y.replace(hour=23, minute=59, second=59)
    if period == "7d":
        return now - timedelta(days=7), now
    if period == "30d":
        return now - timedelta(days=30), now
    if period == "90d":
        return now - timedelta(days=90), now
    if period == "custom" and from_dt and to_dt:
        return datetime.fromisoformat(from_dt), datetime.fromisoformat(to_dt)
    return now - timedelta(hours=24), now


def _bucket_fmt(period):
    return "%H:00" if period in ("today", "yesterday") else "%Y-%m-%d"


class LogEntry(BaseModel):
    user_id: Optional[int] = None
    username: Optional[str] = None
    conv_id: Optional[str] = None
    provider: str = "local"
    model_name: Optional[str] = None
    endpoint: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    ttft_ms: int = 0
    status: str = "success"
    error_detail: Optional[str] = None


@router.post("/log", include_in_schema=False)
async def log_request(entry: LogEntry, db: Session = Depends(get_db)):
    rec = RequestLog(
        user_id=entry.user_id,
        username=entry.username,
        conv_id=entry.conv_id,
        provider=entry.provider,
        model_name=entry.model_name,
        endpoint=entry.endpoint,
        prompt_tokens=entry.prompt_tokens,
        completion_tokens=entry.completion_tokens,
        total_tokens=entry.prompt_tokens + entry.completion_tokens,
        latency_ms=entry.latency_ms,
        ttft_ms=entry.ttft_ms,
        status=entry.status,
        error_detail=entry.error_detail,
        created_at=datetime.utcnow(),
    )
    db.add(rec)
    db.commit()
    return {"ok": True}


@router.get("/summary")
async def get_summary(
    period: str = Query("7d", enum=["today", "yesterday", "7d", "30d", "90d", "custom"]),
    from_dt: Optional[str] = Query(None),
    to_dt: Optional[str] = Query(None),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    start, end = _parse_period(period, from_dt, to_dt)
    rows = db.query(RequestLog).filter(
        RequestLog.created_at >= start,
        RequestLog.created_at <= end,
    ).all()

    if not rows:
        return {
            "period": period, "from": start.isoformat(), "to": end.isoformat(),
            "total_requests": 0, "success": 0, "errors": 0, "success_rate": 100.0,
            "total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "avg_latency_ms": 0, "p95_latency_ms": 0, "p99_latency_ms": 0,
            "avg_tokens_per_request": 0, "top_providers": [], "top_users": [],
        }

    total = len(rows)
    success = sum(1 for r in rows if r.status == "success")
    total_tokens = sum(r.total_tokens or 0 for r in rows)
    prompt_tokens = sum(r.prompt_tokens or 0 for r in rows)
    completion_tokens = sum(r.completion_tokens or 0 for r in rows)
    latencies = sorted([r.latency_ms for r in rows if r.latency_ms])
    avg_lat = int(sum(latencies) / len(latencies)) if latencies else 0
    p95_lat = latencies[int(len(latencies) * 0.95)] if latencies else 0
    p99_lat = latencies[int(len(latencies) * 0.99)] if latencies else 0

    prov_count = Counter(r.provider for r in rows)
    prov_tokens = {}
    for r in rows:
        prov_tokens[r.provider] = prov_tokens.get(r.provider, 0) + (r.total_tokens or 0)
    top_providers = [
        {"provider": p, "requests": c, "tokens": prov_tokens.get(p, 0)}
        for p, c in prov_count.most_common(5)
    ]

    user_stats = {}
    for r in rows:
        key = r.username or f"uid:{r.user_id}" or "anonimo"
        if key not in user_stats:
            user_stats[key] = {"requests": 0, "tokens": 0, "errors": 0}
        user_stats[key]["requests"] += 1
        user_stats[key]["tokens"] += r.total_tokens or 0
        if r.status != "success":
            user_stats[key]["errors"] += 1
    top_users = sorted(
        [{"username": k, **v} for k, v in user_stats.items()],
        key=lambda x: x["tokens"], reverse=True,
    )[:10]

    return {
        "period": period, "from": start.isoformat(), "to": end.isoformat(),
        "total_requests": total, "success": success, "errors": total - success,
        "success_rate": round(success / total * 100, 2),
        "total_tokens": total_tokens, "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "avg_tokens_per_request": round(total_tokens / total, 1),
        "avg_latency_ms": avg_lat, "p95_latency_ms": p95_lat, "p99_latency_ms": p99_lat,
        "top_providers": top_providers, "top_users": top_users,
    }


@router.get("/timeseries")
async def get_timeseries(
    period: str = Query("7d", enum=["today", "yesterday", "7d", "30d", "90d", "custom"]),
    from_dt: Optional[str] = Query(None),
    to_dt: Optional[str] = Query(None),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    start, end = _parse_period(period, from_dt, to_dt)
    fmt = _bucket_fmt(period)
    rows = db.query(RequestLog).filter(
        RequestLog.created_at >= start,
        RequestLog.created_at <= end,
    ).order_by(RequestLog.created_at).all()

    buckets = {}
    for r in rows:
        key = r.created_at.strftime(fmt)
        if key not in buckets:
            buckets[key] = {
                "bucket": key, "requests": 0, "success": 0, "errors": 0,
                "total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0,
                "latencies": [],
            }
        b = buckets[key]
        b["requests"] += 1
        b["success" if r.status == "success" else "errors"] += 1
        b["total_tokens"] += r.total_tokens or 0
        b["prompt_tokens"] += r.prompt_tokens or 0
        b["completion_tokens"] += r.completion_tokens or 0
        if r.latency_ms:
            b["latencies"].append(r.latency_ms)

    result = []
    for b in sorted(buckets.values(), key=lambda x: x["bucket"]):
        lats = sorted(b.pop("latencies"))
        b["avg_latency_ms"] = int(sum(lats) / len(lats)) if lats else 0
        b["p95_latency_ms"] = lats[int(len(lats) * 0.95)] if lats else 0
        result.append(b)

    return {"period": period, "bucket_format": fmt, "data": result}


@router.get("/top-users")
async def get_top_users(
    period: str = Query("30d", enum=["today", "yesterday", "7d", "30d", "90d", "custom"]),
    from_dt: Optional[str] = Query(None),
    to_dt: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    start, end = _parse_period(period, from_dt, to_dt)
    rows = db.query(RequestLog).filter(
        RequestLog.created_at >= start,
        RequestLog.created_at <= end,
    ).all()

    stats = {}
    for r in rows:
        key = r.username or f"uid:{r.user_id}" or "anonimo"
        if key not in stats:
            stats[key] = {"username": key, "requests": 0, "total_tokens": 0,
                          "prompt_tokens": 0, "completion_tokens": 0, "errors": 0, "_lats": []}
        s = stats[key]
        s["requests"] += 1
        s["total_tokens"] += r.total_tokens or 0
        s["prompt_tokens"] += r.prompt_tokens or 0
        s["completion_tokens"] += r.completion_tokens or 0
        if r.status != "success":
            s["errors"] += 1
        if r.latency_ms:
            s["_lats"].append(r.latency_ms)

    result = []
    for s in sorted(stats.values(), key=lambda x: x["total_tokens"], reverse=True)[:limit]:
        lats = s.pop("_lats")
        s["avg_latency_ms"] = int(sum(lats) / len(lats)) if lats else 0
        result.append(s)
    return {"period": period, "users": result}


@router.get("/export")
async def export_logs(
    period: str = Query("30d", enum=["today", "yesterday", "7d", "30d", "90d", "custom"]),
    from_dt: Optional[str] = Query(None),
    to_dt: Optional[str] = Query(None),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    start, end = _parse_period(period, from_dt, to_dt)
    rows = db.query(RequestLog).filter(
        RequestLog.created_at >= start,
        RequestLog.created_at <= end,
    ).order_by(RequestLog.created_at).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "created_at", "username", "user_id", "provider", "model_name",
        "endpoint", "prompt_tokens", "completion_tokens", "total_tokens",
        "latency_ms", "ttft_ms", "status", "error_detail", "conv_id",
    ])
    for r in rows:
        writer.writerow([
            r.id, r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            r.username or "", r.user_id or "", r.provider,
            r.model_name or "", r.endpoint or "",
            r.prompt_tokens, r.completion_tokens, r.total_tokens,
            r.latency_ms, r.ttft_ms, r.status,
            r.error_detail or "", r.conv_id or "",
        ])

    output.seek(0)
    filename = f"orion_metrics_{period}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ─── Tempo Real (Hardware, Processo LLM e Telemetria) ──────────────────────────

@router.get("/realtime")
@router.get("/system")
async def get_system_realtime_metrics(admin: User = Depends(require_admin)):
    """Retorna métricas de CPU, RAM, Disco, Processo llama-server e Telemetria em tempo real."""
    from services.system_metrics_service import get_realtime_metrics
    return await get_realtime_metrics()


@router.get("/stream")
async def stream_realtime_metrics(admin: User = Depends(require_admin)):
    """Stream SSE de métricas de hardware e throughput em tempo real a cada 2 segundos."""
    import json
    from services.system_metrics_service import get_realtime_metrics

    async def event_generator():
        while True:
            try:
                data = await get_realtime_metrics()
                yield f"data: {json.dumps(data)}\n\n"
            except Exception:
                pass
            import asyncio
            await asyncio.sleep(2.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
