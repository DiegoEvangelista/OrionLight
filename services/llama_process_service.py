import asyncio
import logging
import os
import shutil
import signal
import subprocess
import time
from typing import Optional, Tuple

import httpx

from config import get_settings

logger = logging.getLogger("orion_light.llama_process")


class LlamaProcessService:
    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._current_model: Optional[str] = None
        self._port: int = 8085
        self._host: str = "127.0.0.1"

    def _get_configured_port(self) -> int:
        try:
            from urllib.parse import urlparse
            p = urlparse(get_settings().MODEL_URL).port
            if p:
                return p
        except Exception:
            pass
        return self._port

    @property
    def port(self) -> int:
        return self._port

    @property
    def current_model(self) -> Optional[str]:
        return self._current_model

    def has_binary(self) -> bool:
        """Verifica se o binário llama-server está instalado no container/host."""
        return shutil.which("llama-server") is not None or os.path.isfile("/usr/local/bin/llama-server")

    def _get_binary_path(self) -> str:
        b = shutil.which("llama-server")
        if b:
            return b
        if os.path.isfile("/usr/local/bin/llama-server"):
            return "/usr/local/bin/llama-server"
        return "llama-server"

    async def is_healthy(self) -> bool:
        """Verifica se o servidor llama-server está respondendo na porta configurada."""
        url = f"http://{self._host}:{self._port}/health"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(url)
                return r.status_code in (200, 503)
        except Exception:
            return False

    def is_running(self) -> bool:
        if self._process is not None:
            if self._process.poll() is None:
                return True
            else:
                self._process = None
                self._current_model = None
        return False

    def stop_model(self) -> bool:
        """Para o processo do llama-server de forma graciosa e limpa a memória."""
        logger.info("Encerrando processo do llama-server...")
        if self._process is not None:
            try:
                self._process.terminate()
                try:
                    self._process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=2)
            except Exception as e:
                logger.warning("Exceção ao encerrar processo llama-server: %s", e)
            finally:
                self._process = None

        # Garante a eliminação de processos órfãos no sistema
        try:
            os.system("pkill -9 -f llama-server 2>/dev/null || true")
        except Exception:
            pass

        self._current_model = None
        logger.info("llama-server encerrado com sucesso.")
        return True

    def get_process_metrics(self) -> dict:
        """Obtém métricas em tempo real do processo llama-server (CPU, RSS RAM, Threads, Uptime)."""
        empty = {
            "running": False,
            "pid": None,
            "model": None,
            "uptime_seconds": 0,
            "rss_mb": 0.0,
            "rss_gb": 0.0,
            "cpu_percent": 0.0,
            "threads": 0,
        }

        # Verifica se o processo gerenciado está rodando
        if self.is_running() and self._process is not None:
            pid = self._process.pid
            metrics = dict(empty)
            metrics["running"] = True
            metrics["pid"] = pid
            metrics["model"] = self._current_model
            try:
                import psutil
                p = psutil.Process(pid)
                with p.oneshot():
                    metrics["uptime_seconds"] = max(0, int(time.time() - p.create_time()))
                    mem = p.memory_info()
                    metrics["rss_mb"] = round(mem.rss / (1024 * 1024), 1)
                    metrics["rss_gb"] = round(mem.rss / (1024 * 1024 * 1024), 2)
                    metrics["cpu_percent"] = round(p.cpu_percent(interval=None), 1)
                    metrics["threads"] = p.num_threads()
            except Exception:
                pass
            return metrics

        # Se não há processo em self._process, verifica se existe algum llama-server rodando no host
        try:
            import psutil
            for p in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
                p_name = (p.info.get('name') or '').lower()
                cmd = " ".join(p.info.get('cmdline') or []).lower()
                if 'llama-server' in p_name or 'llama-server' in cmd:
                    with p.oneshot():
                        mem = p.memory_info()
                        return {
                            "running": True,
                            "pid": p.pid,
                            "model": self._current_model or "llama-server",
                            "uptime_seconds": max(0, int(time.time() - p.create_time())),
                            "rss_mb": round(mem.rss / (1024 * 1024), 1),
                            "rss_gb": round(mem.rss / (1024 * 1024 * 1024), 2),
                            "cpu_percent": round(p.cpu_percent(interval=None), 1),
                            "threads": p.num_threads(),
                        }
        except Exception:
            pass

        return empty

    async def start_model(
        self,
        filename: str,
        ctx_size: Optional[int] = None,
        gpu_layers: Optional[int] = None,
        threads: Optional[int] = None,
        port: Optional[int] = None,
        **kwargs,
    ) -> Tuple[bool, str]:
        # Compatibilidade com aliases para evitar TypeErrors
        if ctx_size is None:
            ctx_size = kwargs.get("ctx_window") or kwargs.get("context_window") or 4096
        if gpu_layers is None:
            gpu_layers = kwargs.get("gpu_l") or 0
        if threads is None:
            threads = kwargs.get("cpu_threads") or kwargs.get("cpu_t")
        if port is None:
            port = self._get_configured_port()
        """Inicia o llama-server com o modelo GGUF especificado."""
        settings = get_settings()
        models_dir = settings.MODELS_DIR
        model_path = os.path.join(models_dir, filename)

        if not os.path.isfile(model_path):
            # Tenta via symlink model.gguf se filename for genérico
            symlink = os.path.join(models_dir, "model.gguf")
            if os.path.isfile(symlink):
                model_path = symlink
            else:
                return False, f"Arquivo de modelo '{filename}' não encontrado em {models_dir}."

        # Se já está rodando exatamente esse modelo e está saudável, não reinicia
        if self.is_running() and self._current_model == filename:
            if await self.is_healthy():
                return True, "Modelo já está em execução e saudável."

        # Para instância anterior se houver
        self.stop_model()
        await asyncio.sleep(0.5)

        if not self.has_binary():
            return False, "Binário llama-server não está instalado no sistema."

        self._port = port
        bin_path = self._get_binary_path()

        # Cria diretório de logs se não existir
        log_dir = "/data/logs" if os.path.isdir("/data") else "/tmp"
        os.makedirs(log_dir, exist_ok=True)
        log_file_path = os.path.join(log_dir, "llama_server.log")
        log_file = open(log_file_path, "w", encoding="utf-8")

        ngl = max(0, gpu_layers) if gpu_layers is not None else 0

        cmd = [
            bin_path,
            "-m", model_path,
            "--host", "0.0.0.0",
            "--port", str(self._port),
            "-c", str(ctx_size),
            "-ngl", str(ngl),
            "--alias", filename,
        ]

        # Configuração de threads de CPU (0 = automático pelo llama.cpp)
        active_threads = threads if (threads is not None and threads > 0) else getattr(settings, "CPU_THREADS", 0)
        if active_threads and active_threads > 0:
            cmd.extend(["-t", str(active_threads)])

        env = os.environ.copy()
        env["GGML_BACKEND_PATH"] = "/usr/local/lib"
        env["LD_LIBRARY_PATH"] = f"/usr/local/lib:/usr/local/bin:{env.get('LD_LIBRARY_PATH', '')}"

        logger.info("Iniciando llama-server: %s", " ".join(cmd))
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True if os.name != "nt" else False,
            )
        except Exception as e:
            logger.error("Falha ao executar Popen llama-server: %s", e)
            try:
                log_file.close()
            except Exception:
                pass
            return False, f"Falha ao executar binário: {e}"

        # Aguarda inicialização (timeout de 25 segundos)
        logger.info("Aguardando llama-server inicializar na porta %d...", self._port)
        start_time = time.time()
        while time.time() - start_time < 60:
            if self._process.poll() is not None:
                # Processo morreu
                rc = self._process.returncode
                try:
                    log_file.flush()
                    log_file.close()
                except Exception:
                    pass

                try:
                    with open(log_file_path, "r", encoding="utf-8", errors="replace") as f:
                        all_logs = f.read()
                except Exception:
                    all_logs = "Sem logs disponíveis."

                self._process = None
                self._current_model = None

                non_empty = [line.strip() for line in all_logs.splitlines() if line.strip()]
                error_snippet = " \n ".join(non_empty[-6:]) if non_empty else "Nenhuma saída gravada em log."
                logger.error("llama-server morreu logo após iniciar (rc=%s): %s", rc, error_snippet)
                return False, f"Servidor falhou ao carregar modelo (exit code {rc}): {error_snippet}"

            if await self.is_healthy():
                self._current_model = filename
                logger.info("llama-server pronto e saudável com o modelo %s!", filename)
                return True, "Modelo carregado e pronto para uso."

            await asyncio.sleep(0.5)

        # Timeout
        self.stop_model()
        return False, "Tempo limite esgotado aguardando resposta do llama-server."

    def auto_start_from_db(self) -> None:
        """Chamado no boot do Orion Light para religar o modelo ativo."""
        try:
            from database import SessionLocal, ModelConfig
            settings = get_settings()
            with SessionLocal() as db:
                active_cfg = db.query(ModelConfig).filter(ModelConfig.is_active == 1).first()
                if active_cfg:
                    logger.info("Auto-iniciando modelo ativo do banco: %s", active_cfg.filename)
                    ctx = active_cfg.context_window or 8192
                    gpu = active_cfg.gpu_layers or 0
                    th = active_cfg.cpu_threads if (active_cfg.cpu_threads and active_cfg.cpu_threads > 0) else getattr(settings, "CPU_THREADS", 0)
                    asyncio.create_task(self.start_model(active_cfg.filename, ctx_size=ctx, gpu_layers=gpu, threads=th))
        except Exception as e:
            logger.warning("Erro no auto_start_from_db: %s", e)


llama_process_service = LlamaProcessService()
