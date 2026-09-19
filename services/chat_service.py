import json
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from config import get_settings, get_version
from database import Conversation

settings = get_settings()

# ── Identidade Orion (autoritativa em primeira pessoa, concisa, soberana e multilíngue) ─
ORION_SYSTEM_PROMPT = """\
Eu sou o Orion Light, inteligência artificial soberana para suporte técnico, analítico e clínico.

Diretrizes de resposta:
- Falo sempre em primeira pessoa como autoridade técnica no assunto.
- Sou direto, breve e objetivo: respondo com concisão, sem enrolação ou introduções desnecessárias.
- Aprofundo em detalhes e nuances apenas se o usuário solicitar explicitamente.
- Em cálculos e raciocínio lógico, apresento a resolução de forma limpa, direta e exata.
- Respondo com precisão e segurança técnica no idioma em que fui consultado (Português, Inglês ou Espanhol).

DIRETRIZ CRÍTICA DE VERACIDADE E NÃO-ALUCINAÇÃO (SOVEREIGN GROUNDING):
- NUNCA invente, presuma ou deduza dados, relatórios, números de pacientes, agendamentos, estoque ou faturamento de clínicas e hospitais.
- Se o usuário perguntar sobre o status, situação ou dados de uma clínica, hospital ou organização e NÃO houver dados reais fornecidos no contexto ou na pergunta, declare categoricamente que não há dados ou relatórios registrados no momento e oriente o usuário a fornecer os dados ou consultar diretamente o prontuário eletrônico (EHR) ou sistema de gestão correspondente.
- Jamais finja ter acesso a dados ou bancos relacionais que não constam explicitamente no prompt ou contexto fornecido.{context_section}"""


class ChatService:
    def get_or_create_conversation(
        self,
        db: Session,
        user_id: int,
        conv_id: str | None,
    ) -> Conversation:
        if conv_id:
            conv = db.query(Conversation).filter(
                Conversation.id == conv_id,
                Conversation.user_id == user_id,
            ).first()
            if conv:
                return conv

        new_conv = Conversation(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title="Nova conversa",
            messages="[]",
        )
        db.add(new_conv)
        db.commit()
        db.refresh(new_conv)
        return new_conv

    def add_message(self, db: Session, conv_id: str, role: str, content: str) -> None:
        conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
        if not conv:
            return
        msgs = json.loads(conv.messages or "[]")
        msgs.append({"role": role, "content": content})
        conv.messages = json.dumps(msgs, ensure_ascii=False)
        conv.updated_at = datetime.utcnow()
        # Update title from first user message
        if role == "user" and len(msgs) == 1:
            conv.title = content[:60]
        db.commit()

    def get_history(self, db: Session, conv_id: str, max_chars: int) -> list[dict]:
        """Retorna o histórico da conversa com orçamento de chars aplicado."""
        conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
        if not conv:
            return []
        msgs = json.loads(conv.messages or "[]")

        # Budget algorithm: retain most recent messages within character limit
        budget = max_chars
        selected = []
        for m in reversed(msgs):
            cost = len(m.get("content", ""))
            if cost <= budget or not selected:
                selected.append(m)
                budget -= cost
            else:
                break
        selected.reverse()
        return selected

    def persist_exchange(
        self,
        db: Session,
        conv_id: str,
        user_content: str,
        assistant_content: str,
    ) -> None:
        """Adiciona user + assistant messages e atualiza a conversa."""
        conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
        if not conv:
            return
        msgs = json.loads(conv.messages or "[]")
        msgs.append({"role": "user", "content": user_content})
        msgs.append({"role": "assistant", "content": assistant_content})
        conv.messages = json.dumps(msgs, ensure_ascii=False)
        conv.updated_at = datetime.utcnow()
        if not conv.title or conv.title == "Nova conversa":
            conv.title = user_content[:60]
        db.commit()

    def build_orion_system_message(
        self,
        rag_context: str = "",
        web_context: str = "",
    ) -> dict:
        """Constrói a mensagem de sistema com identidade Orion + contexto opcional."""
        context_parts = []
        if rag_context:
            context_parts.append(f"[Base de Conhecimento]\n{rag_context}")
        if web_context:
            context_parts.append(f"[Resultados da Busca Web]\n{web_context}")
        context_section = ("\n\n" + "\n\n".join(context_parts)) if context_parts else ""

        content = ORION_SYSTEM_PROMPT.format(
            context_section=context_section,
        )
        return {"role": "system", "content": content}


chat_service = ChatService()
