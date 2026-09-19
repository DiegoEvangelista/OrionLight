import asyncio
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from config import get_settings
from database import ModelDownload, RequestLog, SessionLocal
from services.llama_process_service import llama_process_service
from services.llm_service import llm_service

logger = logging.getLogger("orion_light.system_metrics")

# Cache to avoid hammering SQLite DB on rapid polling (1.5s cache for telemetry)
_last_telemetry_cache: Dict[str, Any] = {}
_last_telemetry_time: float = 0.0

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


def _get_system_cpu() -> Dict[str, Any]:
    if _HAS_PSUTIL:
        try:
            # interval=None provides immediate non-blocking CPU percent
            pct = psutil.cpu_percent(interval=None)
            logical = psutil.cpu_count(logical=True) or 1
            physical = psutil.cpu_count(logical=False) or logical
            return {
                "percent": round(pct, 1),
                "cores_logical": logical,
                "cores_physical": physical,
            }
        except Exception as e:
            logger.debug("psutil cpu failed: %s", e)

    # Fallback if psutil is unavailable or errors
    return {
        "percent": 0.0,
        "cores_logical": os.cpu_count() or 1,
        "cores_physical": os.cpu_count() or 1,
    }


def _get_system_memory() -> Dict[str, Any]:
    if _HAS_PSUTIL:
        try:
            vm = psutil.virtual_memory()
            return {
                "total_bytes": vm.total,
                "used_bytes": vm.used,
                "available_bytes": vm.available,
                "total_gb": round(vm.total / (1024 ** 3), 2),
                "used_gb": round(vm.used / (1024 ** 3), 2),
                "available_gb": round(vm.available / (1024 ** 3), 2),
                "percent": round(vm.percent, 1),
            }
        except Exception as e:
            logger.debug("psutil memory failed: %s", e)

    # Linux /proc/meminfo fallback
    if os.path.isfile("/proc/meminfo"):
        try:
            meminfo = {}
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        k = parts[0].strip()
                        v = parts[1].strip().split()[0]
                        meminfo[k] = int(v) * 1024
            total = meminfo.get("MemTotal", 0)
            avail = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
            used = max(0, total - avail)
            pct = round((used / total * 100), 1) if total else 0.0
            return {
                "total_bytes": total,
                "used_bytes": used,
                "available_bytes": avail,
                "total_gb": round(total / (1024 ** 3), 2),
                "used_gb": round(used / (1024 ** 3), 2),
                "available_gb": round(avail / (1024 ** 3), 2),
                "percent": pct,
            }
        except Exception:
            pass

    return {
        "total_bytes": 0,
        "used_bytes": 0,
        "available_bytes": 0,
        "total_gb": 0.0,
        "used_gb": 0.0,
        "available_gb": 0.0,
        "percent": 0.0,
    }


def _get_system_disk() -> Dict[str, Any]:
    settings = get_settings()
    target_path = settings.MODELS_DIR
    if not os.path.exists(target_path):
        target_path = "."

    try:
        if _HAS_PSUTIL:
            du = psutil.disk_usage(target_path)
            total = du.total
            used = du.used
            free = du.free
            pct = du.percent
        else:
            du = shutil.disk_usage(target_path)
            total = du.total
            used = du.used
            free = du.free
            pct = round((used / total * 100), 1) if total else 0.0

        return {
            "path": target_path,
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "total_gb": round(total / (1024 ** 3), 2),
            "used_gb": round(used / (1024 ** 3), 2),
            "free_gb": round(free / (1024 ** 3), 2),
            "percent": round(pct, 1),
        }
    except Exception as e:
        logger.debug("disk_usage error: %s", e)
        return {
            "path": target_path,
            "total_bytes": 0,
            "used_bytes": 0,
            "free_bytes": 0,
            "total_gb": 0.0,
            "used_gb": 0.0,
            "free_gb": 0.0,
            "percent": 0.0,
        }


def _get_cached_telemetry_today() -> Dict[str, Any]:
    global _last_telemetry_cache, _last_telemetry_time
    now_ts = time.time()
    if _last_telemetry_cache and (now_ts - _last_telemetry_time < 2.0):
        return _last_telemetry_cache

    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

        with SessionLocal() as db:
            rows = db.query(RequestLog).filter(RequestLog.created_at >= start_of_day).all()
            total = len(rows)
            success = sum(1 for r in rows if r.status == "success")
            total_tokens = sum(r.total_tokens or 0 for r in rows)
            prompt_tokens = sum(r.prompt_tokens or 0 for r in rows)
            completion_tokens = sum(r.completion_tokens or 0 for r in rows)
            latencies = [r.latency_ms for r in rows if r.latency_ms]
            avg_lat = int(sum(latencies) / len(latencies)) if latencies else 0
            sorted_lat = sorted(latencies)
            p95_lat = sorted_lat[int(len(sorted_lat) * 0.95)] if sorted_lat else 0

            ttfts = [r.ttft_ms for r in rows if r.ttft_ms and r.ttft_ms > 0]
            avg_ttft = int(sum(ttfts) / len(ttfts)) if ttfts else 0

            # Estima tokens por segundo médios em geração hoje
            gen_times_ms = [max(10, (r.latency_ms or 0) - (r.ttft_ms or 0)) for r in rows if r.completion_tokens and r.completion_tokens > 0 and r.latency_ms]
            total_gen_time_s = sum(gen_times_ms) / 1000.0 if gen_times_ms else 0.0
            avg_tps = round(completion_tokens / total_gen_time_s, 1) if total_gen_time_s > 0.1 else 0.0

            # Active downloads
            downloads = db.query(ModelDownload).filter(
                ModelDownload.status.in_(["downloading", "pending"])
            ).order_by(ModelDownload.id.desc()).all()

            active_dl_list = [
                {
                    "id": d.id,
                    "filename": d.filename,
                    "repo_id": d.repo_id,
                    "status": d.status,
                    "progress": d.progress or 0.0,
                    "downloaded_bytes": d.downloaded_bytes or 0,
                    "total_bytes": d.total_bytes or 0,
                    "speed": d.speed or "",
                    "eta": d.eta or "",
                }
                for d in downloads
            ]

            data = {
                "total_requests": total,
                "success_rate": round((success / total * 100), 1) if total else 100.0,
                "total_tokens": total_tokens,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "avg_latency_ms": avg_lat,
                "p95_latency_ms": p95_lat,
                "avg_ttft_ms": avg_ttft,
                "avg_tps": avg_tps,
                "active_inferences": llm_service.active_slots,
                "avg_tokens_per_request": round(total_tokens / total, 1) if total else 0,
                "active_downloads": active_dl_list,
            }
            _last_telemetry_cache = data
            _last_telemetry_time = now_ts
            return data
    except Exception as e:
        logger.debug("telemetry cache query error: %s", e)
        return {
            "total_requests": 0,
            "success_rate": 100.0,
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "avg_latency_ms": 0,
            "p95_latency_ms": 0,
            "avg_ttft_ms": 0,
            "avg_tps": 0.0,
            "active_inferences": 0,
            "avg_tokens_per_request": 0,
            "active_downloads": [],
        }


async def get_realtime_metrics() -> Dict[str, Any]:
    """Retorna o snapshot completo de telemetria e métricas de hardware em tempo real."""
    settings = get_settings()

    # Hardware resources
    cpu_data = _get_system_cpu()
    mem_data = _get_system_memory()
    disk_data = _get_system_disk()

    # LLM process metrics
    proc_metrics = llama_process_service.get_process_metrics()
    llm_reachable = await llama_process_service.is_healthy()
    proc_metrics["reachable"] = llm_reachable
    proc_metrics["active_slots"] = llm_service.active_slots
    proc_metrics["parallel_slots"] = settings.PARALLEL_SLOTS
    proc_metrics["model_url"] = settings.MODEL_URL

    # Telemetry today
    telemetry = _get_cached_telemetry_today()

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cpu": cpu_data,
        "memory": mem_data,
        "disk": disk_data,
        "llm_process": proc_metrics,
        "telemetry": telemetry,
    }
