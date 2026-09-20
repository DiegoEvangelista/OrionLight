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


# State tracking for container CPU delta calculations
_last_cgroup_cpu_usec: Optional[float] = None
_last_cgroup_cpu_time: Optional[float] = None


def _read_cgroup_file(path: str) -> Optional[str]:
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return None


def _is_in_container() -> bool:
    if os.path.exists("/.dockerenv"):
        return True
    try:
        if os.path.isfile("/proc/1/cgroup"):
            with open("/proc/1/cgroup", "r", encoding="utf-8") as f:
                content = f.read()
                if "docker" in content or "kubepods" in content or "containerd" in content:
                    return True
    except Exception:
        pass
    return False


def _get_system_cpu() -> Dict[str, Any]:
    global _last_cgroup_cpu_usec, _last_cgroup_cpu_time
    in_container = _is_in_container()

    container_cores: Optional[float] = None
    container_cpu_usec: Optional[float] = None

    # 1. Try cgroup v2
    # Quota: /sys/fs/cgroup/cpu.max (e.g. "400000 100000" or "max 100000")
    # Usage: /sys/fs/cgroup/cpu.stat (line with "usage_usec <num>")
    cpu_max_str = _read_cgroup_file("/sys/fs/cgroup/cpu.max")
    if cpu_max_str:
        parts = cpu_max_str.split()
        if len(parts) >= 2 and parts[0] != "max":
            try:
                quota = float(parts[0])
                period = float(parts[1])
                if quota > 0 and period > 0:
                    container_cores = round(quota / period, 2)
            except (ValueError, ZeroDivisionError):
                pass

        stat_str = _read_cgroup_file("/sys/fs/cgroup/cpu.stat")
        if stat_str:
            for line in stat_str.splitlines():
                if line.startswith("usage_usec"):
                    try:
                        container_cpu_usec = float(line.split()[1])
                        break
                    except (IndexError, ValueError):
                        pass

    # 2. Try cgroup v1
    # Quota: /sys/fs/cgroup/cpu/cpu.cfs_quota_us
    # Period: /sys/fs/cgroup/cpu/cpu.cfs_period_us
    # Usage: /sys/fs/cgroup/cpuacct/cpuacct.usage (nanoseconds)
    if container_cores is None:
        quota_str = _read_cgroup_file("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
        period_str = _read_cgroup_file("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
        if quota_str and period_str:
            try:
                quota = float(quota_str)
                period = float(period_str)
                if quota > 0 and period > 0:
                    container_cores = round(quota / period, 2)
            except (ValueError, ZeroDivisionError):
                pass

        if container_cpu_usec is None:
            acct_str = _read_cgroup_file("/sys/fs/cgroup/cpuacct/cpuacct.usage")
            if acct_str:
                try:
                    container_cpu_usec = float(acct_str) / 1000.0  # ns to us
                except ValueError:
                    pass

    # If container CPU quota is detected:
    if container_cores is not None and container_cores > 0:
        now = time.monotonic()
        calc_pct: Optional[float] = None
        if container_cpu_usec is not None:
            if _last_cgroup_cpu_usec is not None and _last_cgroup_cpu_time is not None:
                dt = now - _last_cgroup_cpu_time
                d_usec = container_cpu_usec - _last_cgroup_cpu_usec
                if dt > 0.1 and d_usec >= 0:
                    spent_sec = d_usec / 1_000_000.0
                    calc_pct = round(min(100.0, max(0.0, (spent_sec / dt / container_cores) * 100.0)), 1)

            _last_cgroup_cpu_usec = container_cpu_usec
            _last_cgroup_cpu_time = now

        # If first tick or delta not ready, use psutil or 0
        if calc_pct is None:
            calc_pct = round(psutil.cpu_percent(interval=None), 1) if _HAS_PSUTIL else 0.0

        return {
            "percent": calc_pct,
            "cores_logical": container_cores,
            "cores_physical": max(1, int(container_cores)),
            "is_container": True,
            "container_limited": True,
        }

    # Host fallback via psutil
    if _HAS_PSUTIL:
        try:
            pct = psutil.cpu_percent(interval=None)
            logical = psutil.cpu_count(logical=True) or 1
            physical = psutil.cpu_count(logical=False) or logical
            return {
                "percent": round(pct, 1),
                "cores_logical": logical,
                "cores_physical": physical,
                "is_container": in_container,
                "container_limited": False,
            }
        except Exception as e:
            logger.debug("psutil cpu failed: %s", e)

    return {
        "percent": 0.0,
        "cores_logical": os.cpu_count() or 1,
        "cores_physical": os.cpu_count() or 1,
        "is_container": in_container,
        "container_limited": False,
    }


def _get_system_memory() -> Dict[str, Any]:
    in_container = _is_in_container()
    host_total = 0
    if _HAS_PSUTIL:
        try:
            host_total = psutil.virtual_memory().total
        except Exception:
            pass

    # 1. Try cgroup v2
    # Limit: /sys/fs/cgroup/memory.max
    # Usage: /sys/fs/cgroup/memory.current
    mem_max_str = _read_cgroup_file("/sys/fs/cgroup/memory.max")
    mem_cur_str = _read_cgroup_file("/sys/fs/cgroup/memory.current")
    if mem_max_str and mem_max_str != "max" and mem_cur_str:
        try:
            limit = int(mem_max_str)
            usage = int(mem_cur_str)
            # Check if realistic limit (not unlimited pseudo-int, e.g. < 1 PiB)
            if 0 < limit < (1024 ** 5):
                used = min(usage, limit)
                avail = max(0, limit - used)
                pct = round((used / limit * 100), 1) if limit else 0.0
                return {
                    "total_bytes": limit,
                    "used_bytes": used,
                    "available_bytes": avail,
                    "total_gb": round(limit / (1024 ** 3), 2),
                    "used_gb": round(used / (1024 ** 3), 2),
                    "available_gb": round(avail / (1024 ** 3), 2),
                    "percent": pct,
                    "is_container": True,
                    "container_limited": True,
                }
        except (ValueError, TypeError):
            pass

    # 2. Try cgroup v1
    # Limit: /sys/fs/cgroup/memory/memory.limit_in_bytes
    # Usage: /sys/fs/cgroup/memory/memory.usage_in_bytes
    v1_lim_str = _read_cgroup_file("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    v1_use_str = _read_cgroup_file("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    if v1_lim_str and v1_use_str:
        try:
            limit = int(v1_lim_str)
            usage = int(v1_use_str)
            # In cgroup v1, unlimited limit is usually 9223372036854771712 or >= host RAM
            if 0 < limit < (1024 ** 5) and (host_total == 0 or limit <= host_total):
                used = min(usage, limit)
                avail = max(0, limit - used)
                pct = round((used / limit * 100), 1) if limit else 0.0
                return {
                    "total_bytes": limit,
                    "used_bytes": used,
                    "available_bytes": avail,
                    "total_gb": round(limit / (1024 ** 3), 2),
                    "used_gb": round(used / (1024 ** 3), 2),
                    "available_gb": round(avail / (1024 ** 3), 2),
                    "percent": pct,
                    "is_container": True,
                    "container_limited": True,
                }
        except (ValueError, TypeError):
            pass

    # 3. Fallback to host psutil
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
                "is_container": in_container,
                "container_limited": False,
            }
        except Exception as e:
            logger.debug("psutil memory failed: %s", e)

    # 4. Fallback to /proc/meminfo
    if os.path.isfile("/proc/meminfo"):
        try:
            meminfo = {}
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
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
                "is_container": in_container,
                "container_limited": False,
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
        "is_container": in_container,
        "container_limited": False,
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
