import asyncio
import json
import os
import tempfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import User, get_db
from routers.auth_router import get_current_user, require_admin
from services.rag_service import rag_service

router = APIRouter(prefix="/v1/rag", tags=["rag"])


class IngestTextRequest(BaseModel):
    doc_id: str
    text: str
    metadata: dict = {}


class QueryRequest(BaseModel):
    query: str
    n_results: int = 5


@router.post("/ingest/text", status_code=status.HTTP_201_CREATED)
async def ingest_text(
    req: IngestTextRequest,
    _: User = Depends(require_admin),
):
    await asyncio.to_thread(rag_service.ingest_text, req.doc_id, req.text, req.metadata)
    return {"detail": "Texto ingerido com sucesso", "doc_id": req.doc_id}


@router.post("/ingest/file", status_code=status.HTTP_201_CREATED)
async def ingest_file(
    file: UploadFile = File(...),
    doc_id: str = Form(...),
    metadata: str = Form(default="{}"),
    _: User = Depends(require_admin),
):
    try:
        meta = json.loads(metadata)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="metadata deve ser JSON válido")

    suffix = os.path.splitext(file.filename or "")[1] or ".txt"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        await asyncio.to_thread(rag_service.ingest_file, tmp_path, doc_id, meta)
    finally:
        os.unlink(tmp_path)

    return {"detail": "Arquivo ingerido com sucesso", "doc_id": doc_id}


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: str,
    _: User = Depends(require_admin),
):
    await asyncio.to_thread(rag_service.delete_document, doc_id)


@router.post("/query")
async def query_rag(
    req: QueryRequest,
    _: User = Depends(require_admin),
):
    results = await asyncio.to_thread(rag_service.query, req.query, req.n_results)
    return {"results": results}
