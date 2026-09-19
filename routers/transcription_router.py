import json
from enum import Enum
from typing import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from database import User
from routers.auth_router import get_current_user
from services.llm_service import llm_service

router = APIRouter(prefix="/v1/transcription", tags=["transcription"])


class RecordTemplate(str, Enum):
    soap = "soap"
    anamnese = "anamnese"
    evolucao = "evolucao"
    custom = "custom"


_TEMPLATES: dict[str, str] = {
    "soap": """\
Organize a transcrição abaixo em formato SOAP:

**S — Subjetivo** (queixas e sintomas relatados pelo paciente)
**O — Objetivo** (dados observados: sinais vitais, exame físico, resultados)
**A — Avaliação** (hipótese diagnóstica / diagnóstico)
**P — Plano** (conduta: medicamentos, exames solicitados, encaminhamentos, retorno)

Seja objetivo e use terminologia médica adequada.
Não invente informações que não estejam na transcrição.
""",
    "anamnese": """\
Organize a transcrição abaixo em formato de Anamnese estruturada:

**Identificação** (nome, idade, sexo — se mencionados)
**Queixa Principal**
**História da Doença Atual (HDA)**
**História Patológica Pregressa (HPP)**
**Medicamentos em uso**
**Alergias**
**História familiar relevante**
**Revisão de sistemas**

Não inclua campos ausentes na transcrição.
""",
    "evolucao": """\
Organize a transcrição abaixo como nota de evolução médica:

**Data/Hora** (se mencionada)
**Evolução clínica** (como o paciente está evoluindo)
**Exames / resultados relevantes**
**Conduta atual**
**Próximos passos**

Seja conciso e direto.
""",
    "custom": "",
}


class TranscriptionRequest(BaseModel):
    text: str
    template: RecordTemplate = RecordTemplate.soap
    custom_template: str | None = None
    max_tokens: int = 2048
    provider: str | None = None
    model: str | None = None


async def _synthesize_stream(
    text: str,
    instructions: str,
    max_tokens: int,
    provider: str | None = None,
    model: str | None = None,
) -> AsyncIterator[str]:
    system = (
        "Você é um assistente médico especializado em documentação clínica. "
        "Sua tarefa é estruturar transcrições de consultas em prontuários claros e precisos. "
        "Use linguagem médica apropriada. Nunca adicione informações não presentes na transcrição."
    )
    user_content = f"{instructions}\n\n---\nTRANSCRIÇÃO:\n{text}\n---"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    async for token in llm_service.stream_chat(
        messages,
        max_tokens=max_tokens,
        provider=provider,
        model=model,
    ):
        yield f"data: {json.dumps({'token': token})}\n\n"

    yield "data: [DONE]\n\n"


@router.post("/synthesize")
async def synthesize(
    req: TranscriptionRequest,
    current_user: User = Depends(get_current_user),
):
    if req.template == RecordTemplate.custom:
        instructions = req.custom_template or _TEMPLATES["soap"]
    else:
        instructions = _TEMPLATES[req.template.value]

    return StreamingResponse(
        _synthesize_stream(
            req.text,
            instructions,
            req.max_tokens,
            provider=req.provider,
            model=req.model,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )



@router.get("/templates")
async def list_templates(current_user: User = Depends(get_current_user)):
    return [t.value for t in RecordTemplate if t != RecordTemplate.custom]
