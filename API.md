# Orion Light — Referência da API

Base URL: `https://<sua-instancia>/`  
Versão: `1.0`  
Formato de dados: JSON para a maioria dos endpoints; `multipart/form-data` para chat (com ou sem arquivo) e uploads RAG; `application/x-www-form-urlencoded` para login

---

## Autenticação

Todos os endpoints (exceto `/health` e `/dashboard`) aceitam autenticação através de qualquer um dos headers padrão da indústria:

```http
Authorization: Bearer <chave_api>
```
ou
```http
x-api-key: <chave_api>
```
ou
```http
api-key: <chave_api>
```

Existem dois tipos de credenciais:

| Tipo | Validade | Uso |
|------|----------|-----|
| **Token de sessão** | 24 horas | Dashboard web, navegadores |
| **API Key** | 365 dias | Integração com outros sistemas, microsserviços, n8n, sistemas EHR/ERP e Agentes de IA |

> **Para Agentes e Sistemas Externos:** Utilize **API Key**. A chave pode ser gerada pelo administrador no painel em *Usuários & API* ou via API com `POST /v1/auth/api-key`. Em caso de comprometimento, pode ser revogada imediatamente com efeito em tempo real via `DELETE /v1/auth/api-key`.

---

## 1. Login

Obtém um token de sessão com usuário e senha.

```
POST /v1/auth/login
Content-Type: application/x-www-form-urlencoded
```

**Body (form-urlencoded):**
```
username=medico01&password=senha123
```

**Resposta 200:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Erro 401:**
```json
{ "detail": "Credenciais inválidas" }
```

**Exemplo JavaScript:**
```js
const form = new URLSearchParams({ username: 'medico01', password: 'senha123' });
const res = await fetch('https://<instancia>/v1/auth/login', {
  method: 'POST',
  body: form,
});
const { access_token } = await res.json();
```

**Exemplo Python:**
```python
import httpx

r = httpx.post('https://<instancia>/v1/auth/login',
    data={'username': 'medico01', 'password': 'senha123'})
token = r.json()['access_token']
```

---

## 2. Chat

### 2.1 Chat com streaming (SSE)

Envia uma mensagem — com ou sem arquivo anexado — e recebe a resposta em tempo real via Server-Sent Events.

```
POST /v1/chat
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

**Campos (form-data):**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `query` | string | ⚠️ | Pergunta ou mensagem. Obrigatório se não enviar `file` |
| `conv_id` | string | ❌ | ID da conversa existente. Omitir cria nova conversa |
| `max_tokens` | int | ❌ | Máximo de tokens na resposta. Padrão: `2048` |
| `enable_search` | bool | ❌ | Ativa busca na internet (DuckDuckGo). Padrão: `false` |
| `file` | file | ❌ | Exame ou documento para análise (ver tipos abaixo) |
| `provider` | string | ❌ | Provedor de IA: `local`, `claude`, `gemini`, `openai`. Padrão: configurado no `.env` |
| `model` | string | ❌ | Nome específico do modelo no provedor (opcional) |


**Tipos de arquivo suportados:**

| Extensão | Processamento |
|----------|--------------|
| `.jpg` `.jpeg` `.png` `.webp` `.gif` | Enviado ao LLM como imagem (requer modelo com visão) |
| `.pdf` | Texto extraído e incluído como contexto |
| `.txt` `.md` `.csv` `.json` | Conteúdo incluído como contexto |

> **Nota sobre imagens:** análise de imagens (RX, ECG, laudos escaneados) só funciona se o servidor LLM estiver rodando um modelo multimodal (Qwen2-VL, LLaVA, Llama 3.2 Vision, etc.). Com modelo texto-only, o arquivo é ignorado.

**Response headers:**
```
Content-Type: text/event-stream
X-Conv-Id: 550e8400-e29b-41d4-a716-446655440000
```

O header `X-Conv-Id` traz o ID da conversa — guarde-o para manter o histórico nas próximas mensagens.

**Formato do stream SSE:**

Cada linha tem o formato `data: <json>\n\n`. O stream **sempre** termina com `data: [DONE]\n\n`, mesmo em caso de erro.

```
data: {"token": "Os"}

data: {"token": " efeitos"}

data: {"token": " colaterais"}

data: [DONE]
```

Em caso de erro interno (LLM indisponível, timeout, etc.), o stream envia um token de erro antes do `[DONE]`:

```
data: {"error": "Erro interno ao processar a mensagem."}

data: [DONE]
```

O cliente deve verificar se cada evento contém `token` ou `error`:

```js
const payload = JSON.parse(data);
if (payload.error) {
  showErrorMessage(payload.error);
} else if (payload.token) {
  appendToOutput(payload.token);
}
```

**Exemplo JavaScript — chat simples (sem arquivo):**
```js
const form = new FormData();
form.append('query', 'Quais são os efeitos colaterais da amoxicilina?');
// form.append('conv_id', convId);  // omitir na primeira mensagem

const res = await fetch('https://<instancia>/v1/chat', {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${token}` },
  body: form,
});

const convId = res.headers.get('X-Conv-Id');
const reader = res.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  const chunk = decoder.decode(value);
  for (const line of chunk.split('\n')) {
    if (!line.startsWith('data: ')) continue;
    const data = line.slice(6);
    if (data === '[DONE]') break;
    const { token } = JSON.parse(data);
    process.stdout.write(token);   // ou append na UI
  }
}
```

**Exemplo JavaScript — com arquivo (exame PDF ou imagem):**
```js
const form = new FormData();
form.append('query', 'Analise este resultado e destaque valores alterados.');
form.append('file', arquivoInput.files[0]);   // <input type="file">
// form.append('conv_id', convId);

const res = await fetch('https://<instancia>/v1/chat', {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${token}` },
  body: form,
});
```

**Exemplo Python — com arquivo:**
```python
import httpx

with httpx.Client() as client:
    with client.stream('POST', 'https://<instancia>/v1/chat',
        headers={'Authorization': f'Bearer {token}'},
        data={'query': 'Analise este exame.'},
        files={'file': ('exame.pdf', open('exame.pdf', 'rb'), 'application/pdf')},
    ) as res:
        conv_id = res.headers.get('X-Conv-Id')
        for line in res.iter_lines():
            if not line.startswith('data: '): continue
            data = line[6:]
            if data == '[DONE]': break
            print(__import__('json').loads(data)['token'], end='', flush=True)
```

**Exemplo Python — texto simples:**
```python
import httpx

with httpx.Client() as client:
    with client.stream('POST', 'https://<instancia>/v1/chat',
        headers={'Authorization': f'Bearer {token}'},
        data={'query': 'Quais os efeitos colaterais da amoxicilina?'},
    ) as res:
        conv_id = res.headers.get('X-Conv-Id')
        for line in res.iter_lines():
            if not line.startswith('data: '):
                continue
            data = line[6:]
            if data == '[DONE]':
                break
            token_text = __import__('json').loads(data)['token']
            print(token_text, end='', flush=True)
```

---

### 2.2 Chat Completions Padrão OpenAI (Agentes de IA, LangChain, SDK Oficial)

Permite integração transparente e plug-and-play com qualquer biblioteca ou agente do ecossistema de IA (OpenAI SDK, LangChain, AutoGen, CrewAI, Dify, Flowise, n8n, etc.). Suporta chamadas com streaming ou síncronas.

```
POST /v1/chat/completions
Authorization: Bearer <api_key>
Content-Type: application/json
```

**Body:**
```json
{
  "model": "local",
  "messages": [
    {"role": "system", "content": "Você é um assistente médico especializado."},
    {"role": "user", "content": "Qual a dosagem usual de amoxicilina em adultos?"}
  ],
  "max_tokens": 2048,
  "temperature": 0.7,
  "stream": false,
  "provider": "local"
}
```

**Exemplo usando o SDK oficial da OpenAI (Python):**
```python
from openai import OpenAI

client = OpenAI(
    base_url="https://<instancia>/v1",
    api_key="<sua_api_key_orion>",
)

# Chamada síncrona
response = client.chat.completions.create(
    model="local",  # ou "claude", "gemini", "openai"
    messages=[
        {"role": "system", "content": "Assistente soberano Orion Light."},
        {"role": "user", "content": "Resuma as contraindicações de anti-inflamatórios em cardiopatas."},
    ],
)
print(response.choices[0].message.content)

# Ou chamada com streaming
stream = client.chat.completions.create(
    model="local",
    messages=[{"role": "user", "content": "Quais exames solicitar na investigação inicial de anemia?"}],
    stream=True,
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

---

### 2.3 Chat via WebSocket

Alternativa ao SSE, útil para ambientes que não suportam streaming HTTP.

```
WebSocket: wss://<instancia>/v1/chat/ws/chat
```

**Primeira mensagem (autenticação + query):**
```json
{
  "token": "<bearer_token>",
  "query": "Quais os efeitos colaterais da amoxicilina?",
  "conv_id": null,
  "max_tokens": 2048
}
```

**Resposta inicial (confirma ID da conversa):**
```json
{ "conv_id": "550e8400-e29b-41d4-a716-446655440000" }
```

**Mensagens subsequentes (tokens da resposta):**
```json
{"token": "Os"}
{"token": " efeitos"}
[DONE]
```

**Exemplo JavaScript:**
```js
const ws = new WebSocket('wss://<instancia>/v1/chat/ws/chat');

ws.onopen = () => {
  ws.send(JSON.stringify({
    token: bearerToken,
    query: 'Quais os efeitos colaterais da amoxicilina?',
    conv_id: null,
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.conv_id) {
    console.log('Conversa:', data.conv_id);
  } else if (data === '[DONE]' || event.data === '[DONE]') {
    ws.close();
  } else if (data.token) {
    process.stdout.write(data.token);
  }
};
```

---

### 2.3 Histórico de conversas

**Listar conversas do usuário:**
```
GET /v1/chat/conversations
Authorization: Bearer <token>
```

**Resposta 200:**
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "Efeitos colaterais da amoxicilina",
    "created_at": "2026-09-17T10:30:00",
    "updated_at": "2026-09-17T10:35:00"
  }
]
```

**Deletar uma conversa:**
```
DELETE /v1/chat/conversations/{conv_id}
Authorization: Bearer <token>
```

Retorna `204 No Content`.

---

## 3. Síntese de Prontuário (Transcrição)

Converte a transcrição de uma consulta em um prontuário estruturado. O stream funciona igual ao chat.

```
POST /v1/transcription/synthesize
Authorization: Bearer <token>
Content-Type: application/json
```

**Body:**
```json
{
  "text": "Paciente chega referindo dor de cabeça há 3 dias...",
  "template": "soap",
  "custom_template": null,
  "max_tokens": 2048
}
```

| Campo | Tipo | Opções | Descrição |
|-------|------|--------|-----------|
| `text` | string | — | Texto da transcrição da consulta |
| `template` | string | `soap`, `anamnese`, `evolucao`, `custom` | Formato do prontuário |
| `custom_template` | string \| null | — | Instruções personalizadas (obrigatório se `template = custom`) |
| `max_tokens` | int | — | Padrão: `2048` |
| `provider` | string \| null | `local`, `claude`, `gemini`, `openai` | Provedor de inferência (opcional) |
| `model` | string \| null | — | Nome do modelo específico (opcional) |


**Templates disponíveis:**

| Template | Estrutura gerada |
|----------|-----------------|
| `soap` | Subjetivo · Objetivo · Avaliação · Plano |
| `anamnese` | Identificação · QP · HDA · HPP · Medicamentos · Alergias · Histórico familiar · Revisão de sistemas |
| `evolucao` | Evolução clínica · Exames · Conduta · Próximos passos |
| `custom` | Livre — definido por `custom_template` |

**Resposta:** stream SSE idêntico ao chat — tokens seguidos de `[DONE]`.

**Listar templates disponíveis:**
```
GET /v1/transcription/templates
Authorization: Bearer <token>
```

**Resposta 200:**
```json
["soap", "anamnese", "evolucao"]
```

**Exemplo JavaScript:**
```js
const res = await fetch('https://<instancia>/v1/transcription/synthesize', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${apiKey}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    text: transcricao,
    template: 'soap',
  }),
});

const reader = res.body.getReader();
const decoder = new TextDecoder();
let prontuario = '';

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  for (const line of decoder.decode(value).split('\n')) {
    if (!line.startsWith('data: ')) continue;
    const data = line.slice(6);
    if (data === '[DONE]') break;
    prontuario += JSON.parse(data).token;
  }
}
```

---

## 4. Base de Conhecimento (RAG)

Permite alimentar o sistema com documentos da clínica (protocolos, bulas, etc.) que serão usados como contexto nas respostas do chat.

> **Todos os endpoints de RAG requerem role `admin`.**

### 4.1 Ingerir arquivo (PDF ou TXT)

```
POST /v1/rag/ingest/file
Authorization: Bearer <admin_token>
Content-Type: multipart/form-data
```

**Form fields:**
| Campo | Tipo | Descrição |
|-------|------|-----------|
| `file` | file | Arquivo PDF ou TXT |
| `doc_id` | string | Identificador único do documento |
| `metadata` | string (JSON) | Metadados opcionais, ex: `{"source": "Protocolo AVC"}` |

**Resposta 201:**
```json
{ "detail": "Arquivo ingerido com sucesso", "doc_id": "protocolo-avc-2026" }
```

**Exemplo Python:**
```python
import httpx

with open('protocolo-avc.pdf', 'rb') as f:
    r = httpx.post('https://<instancia>/v1/rag/ingest/file',
        headers={'Authorization': f'Bearer {admin_key}'},
        files={'file': ('protocolo-avc.pdf', f, 'application/pdf')},
        data={
            'doc_id': 'protocolo-avc-2026',
            'metadata': '{"source": "Protocolo AVC 2026", "categoria": "neurologia"}',
        },
    )
```

### 4.2 Ingerir texto diretamente

```
POST /v1/rag/ingest/text
Authorization: Bearer <admin_token>
Content-Type: application/json
```

```json
{
  "doc_id": "nota-interna-001",
  "text": "Protocolo interno: pacientes com pressão acima de 140/90...",
  "metadata": { "source": "Nota Interna", "autor": "Dr. Silva" }
}
```

**Resposta 201:**
```json
{ "detail": "Texto ingerido com sucesso", "doc_id": "nota-interna-001" }
```

### 4.3 Remover documento

```
DELETE /v1/rag/documents/{doc_id}
Authorization: Bearer <admin_token>
```

Retorna `204 No Content`. Remove todos os chunks do documento.

---

## 5. Gerenciamento de Modelos & Provedores Externos

### 5.1 Listagem de Modelos Disponíveis (Padrão OpenAI)

Utilizado por clientes OpenAI, LangChain, n8n, OpenWebUI e agentes para listar os modelos disponíveis no gateway:

```
GET /v1/models
Authorization: Bearer <token>
```

**Resposta 200 (Formato OpenAI):**
```json
{
  "object": "list",
  "data": [
    {
      "id": "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
      "object": "model",
      "created": 1773950000,
      "owned_by": "local-disk",
      "permission": [],
      "root": "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
      "parent": null
    },
    {
      "id": "claude-3-5-sonnet-20241022",
      "object": "model",
      "created": 1773950000,
      "owned_by": "claude",
      "permission": [],
      "root": "claude-3-5-sonnet-20241022",
      "parent": null
    }
  ]
}
```

### 5.2 Status dos Provedores

```
GET /v1/models/providers
Authorization: Bearer <token>
```

Retorna o provedor padrão configurado e o status das chaves de API (`local`, `claude`, `gemini`, `openai`).

### 5.2 Buscar Modelos GGUF no Hugging Face

```
GET /v1/models/hf/search?q=Qwen&limit=15
Authorization: Bearer <token>
```

Retorna repositórios com downloads, autor, tags e data de modificação.

### 5.3 Listar Arquivos GGUF de um Repositório

```
GET /v1/models/hf/files?repo_id=unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF
Authorization: Bearer <token>
```

Retorna cada arquivo `.gguf`, identificação da quantização (`Q4_K_M`, `Q8_0`, etc.) e tamanho em MB/GB.

### 5.4 Iniciar Download em Background

> Requer role `admin`.

```
POST /v1/models/hf/download
Authorization: Bearer <admin_token>
Content-Type: application/json
```

```json
{
  "repo_id": "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF",
  "filename": "Qwen3-Coder-30B-A3B-Instruct-UD-IQ1_S.gguf"
}
```

### 5.5 Monitorar Downloads e Cancelamento

```
GET /v1/models/downloads
Authorization: Bearer <admin_token>
```

Retorna progresso (`progress` em %, `speed` em MB/s, `eta`, `status`).  
Para cancelar ou remover registro: `DELETE /v1/models/downloads/{download_id}`.

### 5.6 Gerenciar, Configurar e Ativar Modelos Locais

- **Listar modelos com parâmetros e status:** `GET /v1/models/local` (Bearer token)
  - Retorna para cada modelo `.gguf`: tamanho, data, `context_window`, `gpu_layers`, `loading_strategy` e `is_active`.
- **Configurar parâmetros do modelo:** `PUT /v1/models/local/{filename}/config` (Requer role `admin`)
  - Permite configurar janela de contexto (`context_window`), camadas na GPU (`gpu_layers`) e estratégia de carregamento (`loading_strategy`: `keep_warm` ou `on_demand`).
- **Ativar modelo para inferência imediata:** `POST /v1/models/local/{filename}/activate` (Requer role `admin`)
  - Define o modelo como ativo (`is_active=1`) no banco de dados e sincroniza `MODEL_FILE` e `CTX_SIZE` no `.env` para apontar diretamente para o arquivo selecionado, sem duplicar dados em disco.
- **Desativar modelo:** `POST /v1/models/local/{filename}/deactivate` (Requer role `admin`)
- **Deletar modelo do disco:** `DELETE /v1/models/local/{filename}` (Requer role `admin`)

### 5.7 Configurações do Sistema em Tempo Real

- **Visualizar configurações:** `GET /v1/admin/settings` (Requer role `admin`)
- **Atualizar e persistir configurações:** `PUT /v1/admin/settings` (Requer role `admin`)
  - Permite atualizar `DEFAULT_PROVIDER`, `MODEL_URL`, `PARALLEL_SLOTS`, `MAX_CONTEXT_CHARS`, `SEARCH_MAX_RESULTS`, além das chaves e modelos de provedores externos (`ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `OPENAI_API_KEY`, `OPENAI_MODEL`). As alterações são sincronizadas no `.env` e aplicadas imediatamente sem necessidade de reiniciar o container.

---

## 6. Saúde do sistema

```
GET /health
```

Não requer autenticação.

**Resposta 200:**
```json
{
  "status": "ok",
  "llm_reachable": true
}
```


---

## Códigos de erro comuns

| Código | Situação |
|--------|----------|
| `401` | Token ausente, inválido ou expirado (ou API Key revogada) |
| `403` | Usuário autenticado mas sem permissão (ex: endpoint admin acessado por role `user`) |
| `400` | Body inválido ou parâmetro incorreto (ex: nenhuma query nem arquivo enviado) |
| `404` | Recurso não encontrado |
| `415` | Tipo de arquivo não suportado no chat (use JPG, PNG, WebP, PDF, TXT) |
| `500` | Erro interno do servidor |

Todos os erros retornam:
```json
{ "detail": "Descrição do erro" }
```

---

## Guia de Integração para Sistemas Externos (Backends, EHR e Microsserviços)

### Fluxo recomendado para o prontuário

```
1. No login do operador/médico no sistema externo:
   → POST /v1/auth/login  (ou use API Key já configurada)
   → Guarde o token na sessão do usuário

2. Ao abrir o chat de assistência:
   → POST /v1/chat  com conv_id=null
   → Guarde o X-Conv-Id retornado no header
   → Use o conv_id nas próximas mensagens da mesma consulta

3. Ao finalizar transcrição da consulta:
   → POST /v1/transcription/synthesize  com template="soap"
   → Faça stream do resultado para o campo do prontuário

4. Para alimentar a base com protocolos da clínica (one-time):
   → POST /v1/rag/ingest/file  com a API Key admin
```

### Usando API Key (recomendado para integração de sistema)

Gere a API Key no dashboard (`/dashboard`) em **Usuários → 🔑 API Key**.

```js
// Guarde a API Key como variável de ambiente no seu backend ou microsserviço
const ORION_API_KEY = process.env.ORION_LIGHT_API_KEY;

// Requisições JSON (transcrição, RAG text, etc.)
const jsonHeaders = {
  'Authorization': `Bearer ${ORION_API_KEY}`,
  'Content-Type': 'application/json',
};

// Requisições multipart (chat — com ou sem arquivo)
// NÃO defina Content-Type manualmente: o FormData seta o boundary automaticamente
const chatHeaders = {
  'Authorization': `Bearer ${ORION_API_KEY}`,
};
```

A API Key não expira em 24h — é válida por 365 dias. Pode ser revogada instantaneamente pelo dashboard se comprometida.

### Variáveis de Configuração no Sistema Externo

```env
ORION_LIGHT_URL=https://<instancia-da-clinica>
ORION_LIGHT_API_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

## 8. Telemetria, Histórico de Consumo & Relatórios

O Orion Light monitora e persiste cada requisição de inferência realizada pelo gateway (tokens consumidos, tempo até o primeiro token TTFT, latência total, modelo, provedor utilizado e status de sucesso/falha).

Todos os endpoints desta seção requerem perfil de administrador (`role: admin`).

### 8.1 Resumo de Métricas por Período

Retorna os principais KPIs de desempenho consolidados no intervalo selecionado:

```
GET /v1/metrics/summary?period=7d
Authorization: Bearer <admin_token>
```

**Parâmetros de Query:**
- `period`: `today` | `yesterday` | `7d` (padrão) | `30d` | `90d` | `custom`
- `from_dt`: data de início ISO 8601 (obrigatório se `period=custom`)
- `to_dt`: data de fim ISO 8601 (obrigatório se `period=custom`)

**Resposta 200:**
```json
{
  "period": "7d",
  "from": "2026-09-11T22:00:00",
  "to": "2026-09-18T22:00:00",
  "total_requests": 1420,
  "success": 1412,
  "errors": 8,
  "success_rate": 99.44,
  "total_tokens": 1284500,
  "prompt_tokens": 820300,
  "completion_tokens": 464200,
  "avg_tokens_per_request": 904.6,
  "avg_latency_ms": 740,
  "p95_latency_ms": 1650,
  "p99_latency_ms": 2890,
  "top_providers": [
    {"provider": "local", "requests": 1200, "tokens": 1050000},
    {"provider": "claude", "requests": 220, "tokens": 234500}
  ]
}
```

### 8.2 Série Temporal (Gráficos)

Retorna dados agrupados em buckets de tempo (por hora para `today`/`yesterday` ou por dia para `7d`/`30d`/`90d`):

```
GET /v1/metrics/timeseries?period=7d
Authorization: Bearer <admin_token>
```

### 8.3 Ranking de Consumo por Usuário / Sistema

Retorna os usuários e chaves de API com maior consumo de tokens e requisições:

```
GET /v1/metrics/top-users?period=30d&limit=10
Authorization: Bearer <admin_token>
```

### 8.4 Exportação de Relatórios em CSV

Gera e faz o download de arquivo CSV contendo a trilha completa de auditoria e consumo de cada requisição do período:

```
GET /v1/metrics/export?period=30d
Authorization: Bearer <admin_token>
```

**Cabeçalhos do CSV exportado:**
`id,created_at,username,user_id,provider,model_name,endpoint,prompt_tokens,completion_tokens,total_tokens,latency_ms,ttft_ms,status,error_detail,conv_id`


