import logging
import os
import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import get_settings
from database import ModelDownload, SessionLocal

logger = logging.getLogger("orion_light.hf")
# NOTE: não cacheie settings aqui em nível de módulo pois update_env_config limpa o cache.
# Acesse sempre via get_settings() para garantir valores atualizados.


class HFService:
    def __init__(self):
        self._active_downloads: Dict[int, threading.Event] = {}
        self._models_dir_cache: Optional[str] = None

    def _get_models_dir(self) -> str:
        if self._models_dir_cache:
            return self._models_dir_cache
        mdir = get_settings().MODELS_DIR
        try:
            os.makedirs(mdir, exist_ok=True)
            self._models_dir_cache = mdir
            return mdir
        except OSError:
            # Fallback seguro para ambientes de desenvolvimento ou sem permissão em /data
            fallback = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
            os.makedirs(fallback, exist_ok=True)
            self._models_dir_cache = fallback
            return fallback

    def _validate_safe_filename(self, filename: str) -> str:
        safe = os.path.basename(filename).strip()
        if not safe or ".." in safe or safe.startswith("/"):
            raise ValueError("Nome de arquivo inválido.")
        if not safe.lower().endswith(".gguf"):
            raise ValueError("Apenas arquivos .gguf são permitidos.")
        return safe

    def search_models(self, query: str = "", limit: int = 18) -> List[Dict[str, Any]]:
        """Busca modelos GGUF no Hugging Face com suporte a busca trending e tags."""
        try:
            from huggingface_hub import HfApi
            api = HfApi()
            q = query.strip()
            search_query = q if q else "gguf"

            models = []
            try:
                models = list(api.list_models(
                    search=search_query,
                    limit=limit,
                    sort="downloads",
                    filter="gguf",
                ))
            except Exception as e_filt:
                logger.warning("Busca HF com filtro 'gguf' falhou: %s. Tentando sem filtro...", e_filt)
                models = list(api.list_models(
                    search=f"{search_query} gguf",
                    limit=limit,
                    sort="downloads",
                ))

            # Se busca por termo específico veio vazia, tenta sem filtro restritivo
            if not models and q:
                try:
                    models = list(api.list_models(
                        search=f"{q} gguf",
                        limit=limit,
                        sort="downloads",
                    ))
                except Exception:
                    pass

            results = []
            for m in models:
                m_id = getattr(m, "id", None) or getattr(m, "modelId", "")
                if not m_id:
                    continue

                # Extração correta de autor com fallback para o namespace do repo
                author = getattr(m, "author", None)
                if not author:
                    author = m_id.split("/")[0] if "/" in m_id else "comunidade"

                tags = getattr(m, "tags", []) or []

                # Extrai label de tamanho do modelo (ex: 3B, 7B, 8B, 14B, 32B, 70B)
                size_label = None
                for candidate in [m_id] + tags:
                    match = re.search(r'\b(\d+(?:\.\d+)?[bB])\b', str(candidate))
                    if match:
                        size_label = match.group(1).upper()
                        break

                results.append({
                    "id": m_id,
                    "author": author,
                    "downloads": getattr(m, "downloads", 0) or 0,
                    "likes": getattr(m, "likes", 0) or 0,
                    "lastModified": getattr(m, "lastModified", None) or getattr(m, "last_modified", None),
                    "tags": tags[:6],
                    "size_label": size_label or "GGUF",
                })
            return results
        except Exception as e:
            logger.error("Erro na busca HuggingFace: %s", e)
            raise RuntimeError(f"Falha ao conectar com Hugging Face Hub: {e}")

    def list_repo_files(self, repo_id: str) -> List[Dict[str, Any]]:
        """Lista arquivos .gguf disponíveis no repositório com tamanho e quantização."""
        try:
            from huggingface_hub import HfApi
            api = HfApi()
            info = api.model_info(repo_id=repo_id, files_metadata=True)
            files = []
            for f in info.siblings:
                rname = f.rfilename
                if rname.lower().endswith(".gguf"):
                    size_bytes = f.size or 0
                    size_mb = round(size_bytes / (1024 * 1024), 2)
                    size_gb = round(size_bytes / (1024 * 1024 * 1024), 2)

                    # Detecta quantização avançada
                    quant = "Outro"
                    q_match = re.search(r'(Q[0-9]_[A-Z0-9_]+|IQ[0-9]_[A-Z0-9_]+|FP16|BF16|Q[0-9]_0|Q[0-9]_1)', rname, re.IGNORECASE)
                    if q_match:
                        quant = q_match.group(1).upper()
                    elif "q4_k_m" in rname.lower():
                        quant = "Q4_K_M (Equilibrado)"
                    elif "q5_k_m" in rname.lower():
                        quant = "Q5_K_M (Alta Qualidade)"
                    elif "q8_0" in rname.lower():
                        quant = "Q8_0 (Lossless)"
                    elif "q2_" in rname.lower():
                        quant = "Q2 (Comprimido)"
                    elif "q3_" in rname.lower():
                        quant = "Q3 (Compacto)"

                    files.append({
                        "filename": rname,
                        "size_mb": size_mb,
                        "size_gb": size_gb,
                        "size_bytes": size_bytes,
                        "quantization": quant,
                    })

            return sorted(files, key=lambda x: x["size_mb"])
        except Exception as e:
            logger.error("Erro ao listar arquivos do repo %s: %s", repo_id, e)
            raise RuntimeError(f"Falha ao obter arquivos do repositório {repo_id}: {e}")

    def start_download(self, repo_id: str, filename: str, auto_activate: bool = False) -> Dict[str, Any]:
        """Registra o download no banco e inicia o processo em background thread."""
        filename = self._validate_safe_filename(filename)
        models_dir = self._get_models_dir()
        target_path = os.path.join(models_dir, filename)

        if os.path.exists(target_path):
            return {
                "status": "exists",
                "message": f"O modelo {filename} já existe no diretório local.",
                "path": target_path,
            }

        db = SessionLocal()
        try:
            download = ModelDownload(
                repo_id=repo_id,
                filename=filename,
                status="downloading",
                progress=0.0,
                downloaded_bytes=0,
                total_bytes=0,
            )
            db.add(download)
            db.commit()
            db.refresh(download)
            download_id = download.id
        finally:
            db.close()

        cancel_event = threading.Event()
        self._active_downloads[download_id] = cancel_event

        thread = threading.Thread(
            target=self._download_worker,
            args=(download_id, repo_id, filename, target_path, cancel_event, auto_activate),
            daemon=True,
        )
        thread.start()

        return {
            "status": "downloading",
            "download_id": download_id,
            "repo_id": repo_id,
            "filename": filename,
        }

    def _download_worker(
        self,
        download_id: int,
        repo_id: str,
        filename: str,
        target_path: str,
        cancel_event: threading.Event,
        auto_activate: bool = False,
    ):
        part_path = f"{target_path}.part"
        start_time = time.time()
        last_update_time = 0.0

        try:
            import httpx
            url = f"https://huggingface.co/{repo_id}/resolve/main/{filename}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "*/*",
            }

            downloaded = 0
            file_mode = "wb"

            # Suporte a retomada (Resume) se arquivo parcial existir
            if os.path.exists(part_path):
                existing_size = os.path.getsize(part_path)
                if existing_size > 0:
                    downloaded = existing_size
                    headers["Range"] = f"bytes={downloaded}-"
                    file_mode = "ab"
                    logger.info("Retomando download de %s a partir de %d bytes", filename, downloaded)

            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(connect=20.0, read=120.0, write=20.0, pool=10.0)) as client:
                with client.stream("GET", url, headers=headers) as resp:
                    if resp.status_code == 416:
                        # Arquivo já baixado por completo
                        total_bytes = downloaded
                    elif resp.status_code == 206:
                        # Retomado com sucesso
                        content_len = int(resp.headers.get("content-length", 0))
                        total_bytes = downloaded + content_len
                    elif resp.status_code == 200:
                        # Servidor enviou arquivo completo (sem resume)
                        downloaded = 0
                        file_mode = "wb"
                        total_bytes = int(resp.headers.get("content-length", 0))
                    else:
                        raise RuntimeError(f"HuggingFace retornou HTTP {resp.status_code}")

                    db = SessionLocal()
                    try:
                        rec = db.query(ModelDownload).filter(ModelDownload.id == download_id).first()
                        if rec:
                            rec.total_bytes = total_bytes
                            rec.status = "downloading"
                            db.commit()
                    finally:
                        db.close()

                    with open(part_path, file_mode) as f:
                        for chunk in resp.iter_bytes(chunk_size=1024 * 512):  # 512 KB chunks
                            if cancel_event.is_set():
                                raise InterruptedError("Download cancelado pelo usuário.")
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)

                            now = time.time()
                            # Atualiza progresso no banco a cada 2 segundos (reduz I/O SQLite)
                            if now - last_update_time >= 2.0 or (total_bytes and downloaded >= total_bytes):
                                last_update_time = now
                                elapsed = now - start_time
                                speed_bps = (downloaded - (existing_size if file_mode == "ab" else 0)) / elapsed if elapsed > 0 else 0
                                speed_str = f"{round(speed_bps / (1024 * 1024), 1)} MB/s"

                                if total_bytes > 0:
                                    prog = round((downloaded / total_bytes) * 100, 1)
                                    rem_bytes = max(0, total_bytes - downloaded)
                                    rem_sec = rem_bytes / speed_bps if speed_bps > 0 else 0
                                    eta_str = f"{int(rem_sec // 60)}m {int(rem_sec % 60)}s"
                                else:
                                    prog = 0.0
                                    eta_str = "calculando..."

                                # Abre/commita/fecha apenas aqui, 1x a cada 2s
                                db_prog = SessionLocal()
                                try:
                                    rec = db_prog.query(ModelDownload).filter(ModelDownload.id == download_id).first()
                                    if rec:
                                        rec.progress = min(100.0, prog)
                                        rec.downloaded_bytes = downloaded
                                        rec.speed = speed_str
                                        rec.eta = eta_str
                                        rec.updated_at = datetime.utcnow()
                                        db_prog.commit()
                                finally:
                                    db_prog.close()

            # Concluído com sucesso: renomeia o arquivo temporário
            if os.path.exists(part_path):
                if os.path.exists(target_path):
                    os.remove(target_path)
                os.rename(part_path, target_path)

            db = SessionLocal()
            try:
                rec = db.query(ModelDownload).filter(ModelDownload.id == download_id).first()
                if rec:
                    rec.status = "completed"
                    rec.progress = 100.0
                    rec.downloaded_bytes = os.path.getsize(target_path)
                    rec.speed = "Concluído"
                    rec.eta = "0s"
                    rec.updated_at = datetime.utcnow()
                    db.commit()
            finally:
                db.close()

            if auto_activate:
                try:
                    logger.info("Auto-ativando modelo baixado %s...", filename)
                    from database import ModelConfig
                    with SessionLocal() as db_act:
                        db_act.query(ModelConfig).update({ModelConfig.is_active: 0})
                        cfg = db_act.query(ModelConfig).filter(ModelConfig.filename == filename).first()
                        if not cfg:
                            cfg = ModelConfig(filename=filename, is_active=1, context_window=8192, gpu_layers=0)
                            db_act.add(cfg)
                        else:
                            cfg.is_active = 1
                        db_act.commit()

                    self.activate_local_model(filename)

                    from services.llama_process_service import llama_process_service
                    from config import get_settings
                    s = get_settings()
                    th = getattr(s, "CPU_THREADS", 4)

                    import asyncio
                    try:
                        # Em background threads de download, executa via asyncio.run diretamente
                        asyncio.run(llama_process_service.start_model(filename, ctx_size=4096, gpu_layers=0, threads=th))
                    except Exception as e_start:
                        logger.warning("Falha ao iniciar llama-server apos download de %s: %s", filename, e_start)
                except Exception as e_act:
                    logger.warning("Falha ao auto-ativar modelo %s após download: %s", filename, e_act)

        except InterruptedError:
            logger.info("Download %s (%s) cancelado.", download_id, filename)
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except Exception:
                    pass
            db = SessionLocal()
            try:
                rec = db.query(ModelDownload).filter(ModelDownload.id == download_id).first()
                if rec:
                    rec.status = "cancelled"
                    rec.updated_at = datetime.utcnow()
                    db.commit()
            finally:
                db.close()

        except Exception as e:
            logger.error("Erro no download %s (%s): %s", download_id, filename, e)
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except Exception:
                    pass
            db = SessionLocal()
            try:
                rec = db.query(ModelDownload).filter(ModelDownload.id == download_id).first()
                if rec:
                    rec.status = "failed"
                    rec.error_message = str(e)
                    rec.updated_at = datetime.utcnow()
                    db.commit()
            finally:
                db.close()
        finally:
            self._active_downloads.pop(download_id, None)

    def cancel_download(self, download_id: int) -> bool:
        """Cancela um download ativo."""
        event = self._active_downloads.get(download_id)
        if event:
            event.set()
            return True
        return False

    def list_local_models(self) -> List[Dict[str, Any]]:
        """Lista os arquivos .gguf existentes no MODELS_DIR (exclui cópias residuais model.gguf)."""
        models_dir = self._get_models_dir()
        files = []
        if os.path.isdir(models_dir):
            for fname in sorted(os.listdir(models_dir)):
                if fname.lower().endswith(".gguf") and fname.lower() != "model.gguf":
                    fpath = os.path.join(models_dir, fname)
                    try:
                        st = os.stat(fpath)
                        size_bytes = st.st_size
                        size_gb = round(size_bytes / (1024 * 1024 * 1024), 2)
                        size_mb = round(size_bytes / (1024 * 1024), 1)
                        modified = datetime.fromtimestamp(st.st_mtime).isoformat()
                    except OSError:
                        size_gb, size_mb, modified = 0.0, 0.0, None

                    is_asr = any(k in fname.lower() for k in ["asr", "whisper", "speech", "audio", "tts"])
                    files.append({
                        "name": fname,
                        "size_gb": size_gb,
                        "size_mb": size_mb,
                        "modified_at": modified,
                        "path": fpath,
                        "is_chat_compatible": not is_asr,
                        "model_type": "asr" if is_asr else "chat",
                    })
        return files

    def delete_local_model(self, filename: str) -> bool:
        """Deleta com segurança um arquivo de modelo local."""
        filename = self._validate_safe_filename(filename)
        models_dir = self._get_models_dir()
        fpath = os.path.join(models_dir, filename)
        if os.path.isfile(fpath):
            os.remove(fpath)
            return True
        return False

    def activate_local_model(self, filename: str) -> bool:
        """Ativa o modelo .gguf diretamente sem criar ou duplicar arquivos no disco."""
        safe_name = self._validate_safe_filename(filename)
        models_dir = self._get_models_dir()
        source_path = os.path.join(models_dir, safe_name)
        if not os.path.isfile(source_path):
            raise FileNotFoundError(f"Arquivo de modelo {safe_name} não encontrado em {models_dir}")

        # Mantém compatibilidade com contêineres/serviços que usam model.gguf como padrão
        # criando um link simbólico leve (sem duplicar arquivos físicos no disco)
        symlink_target = os.path.join(models_dir, "model.gguf")
        if os.path.lexists(symlink_target) and os.path.abspath(source_path) != os.path.abspath(symlink_target):
            try:
                os.remove(symlink_target)
            except Exception:
                pass
        try:
            os.symlink(source_path, symlink_target)
            logger.info("Symlink model.gguf criado apontando para %s", safe_name)
        except (OSError, NotImplementedError):
            pass

        logger.info("Modelo %s ativado com sucesso.", safe_name)
        return True

    def deactivate_local_model(self, filename: Optional[str] = None) -> bool:
        """Remove o link simbólico model.gguf e desativa o modelo em disco."""
        models_dir = self._get_models_dir()
        symlink_target = os.path.join(models_dir, "model.gguf")
        if os.path.lexists(symlink_target):
            try:
                os.remove(symlink_target)
                logger.info("Symlink model.gguf removido com sucesso.")
            except Exception as e:
                logger.warning("Falha ao remover symlink model.gguf: %s", e)
        return True

    def get_active_model_filename(self) -> Optional[str]:
        """Obtém o nome do arquivo atualmente ativo a partir do banco de dados ou ambiente."""
        try:
            from database import SessionLocal, ModelConfig
            with SessionLocal() as db:
                active_cfg = db.query(ModelConfig).filter(ModelConfig.is_active == 1).first()
                if active_cfg:
                    return active_cfg.filename
                has_configs = db.query(ModelConfig).count()
                if has_configs > 0:
                    return None
        except Exception:
            pass

        # Fallback para variável de ambiente apenas se não houver registros no banco
        env_model = os.environ.get("MODEL_FILE")
        if env_model and env_model != "model.gguf" and env_model.strip() != "":
            return env_model
        return None

    def ensure_default_model_bootstrap(self) -> None:
        """Verifica se já existe modelo local ou download em andamento; se não, inicia download do modelo padrão."""
        settings = get_settings()
        models_dir = self._get_models_dir()
        target_file = getattr(settings, "AUTO_DOWNLOAD_FILE", "Qwen2.5-7B-Instruct-Q4_K_M.gguf")
        repo_id = getattr(settings, "AUTO_DOWNLOAD_MODEL", "bartowski/Qwen2.5-7B-Instruct-GGUF")
        target_path = os.path.join(models_dir, target_file)

        # 1. Se o arquivo já existe no disco
        if os.path.isfile(target_path):
            try:
                from database import SessionLocal, ModelConfig
                with SessionLocal() as db:
                    active = db.query(ModelConfig).filter(ModelConfig.is_active == 1).first()
                    if not active:
                        cfg = db.query(ModelConfig).filter(ModelConfig.filename == target_file).first()
                        if not cfg:
                            cfg = ModelConfig(filename=target_file, is_active=1, context_window=8192, gpu_layers=0, cpu_threads=getattr(settings, "CPU_THREADS", 4))
                            db.add(cfg)
                        else:
                            cfg.is_active = 1
                        db.commit()
                        self.activate_local_model(target_file)
            except Exception as e:
                logger.warning("Erro ao registrar modelo existente no bootstrap: %s", e)
            return

        # 2. Verifica se já há QUALQUER modelo .gguf ativo no banco ou no disco
        try:
            from database import SessionLocal, ModelConfig, ModelDownload
            with SessionLocal() as db:
                active = db.query(ModelConfig).filter(ModelConfig.is_active == 1).first()
                if active:
                    active_path = os.path.join(models_dir, active.filename)
                    if os.path.isfile(active_path):
                        return

                in_progress = db.query(ModelDownload).filter(
                    ModelDownload.filename == target_file,
                    ModelDownload.status.in_(["downloading", "pending"])
                ).first()
                if in_progress:
                    logger.info("Download de bootstrap de %s já em andamento (id=%s)", target_file, in_progress.id)
                    return
        except Exception as e:
            logger.warning("Erro ao verificar downloads no banco: %s", e)

        # 3. Dispara o download em background do modelo padrão
        logger.info("Auto-bootstrap: iniciando download inicial de %s (%s)...", repo_id, target_file)
        try:
            self.start_download(repo_id, target_file, auto_activate=True)
        except Exception as e:
            logger.error("Falha ao iniciar auto-bootstrap do modelo: %s", e)


hf_service = HFService()
