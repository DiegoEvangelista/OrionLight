// ════════════════════════════════════════════════════════════════════════════════
// Orion Light — Internationalization (i18n) Engine
// Supported: pt (Português), en (English), es (Español)
// ════════════════════════════════════════════════════════════════════════════════

const ORION_TRANSLATIONS = {
  pt: {
    // Brand & Header
    brand_sub: "Plataforma Soberana de IA & Gateway de Modelos",
    nav_status: "Status Geral",
    nav_chat: "Playground de Teste",
    nav_models: "Gestão de Modelos",
    nav_reports: "Relatórios & Métricas",
    nav_users: "Usuários & API",
    nav_settings: "Configurações",
    btn_logout: "Sair",
    slots_active: "slots ativos",
    realtime_badge: "TEMPO REAL",
    btn_pause: "⏸️ Pausar",
    btn_resume: "▶️ Retomar",

    // Login
    login_subtitle: "Plataforma de Inteligência & Gateway de Modelos",
    login_user_label: "Usuário",
    login_user_ph: "admin",
    login_pass_label: "Senha",
    login_pass_ph: "••••••••",
    login_btn: "Autenticar",
    login_err_default: "Credenciais inválidas",
    login_err_net: "Erro de conexão com o servidor",

    // Status Tab
    status_title: "Telemetria & Status",
    status_subtitle: "Visão geral do gateway, recursos de hardware e throughput de inferência em tempo real.",
    status_hw_title: "Recursos de Hardware & Processo LLM",
    status_hw_subtitle: "Métricas computadas a cada 2s direto do host e processo nativo.",
    status_throughput_title: "Throughput & Performance (Tempo Real / Hoje)",
    status_throughput_subtitle: "Taxa de sucesso, latência e consumo de tokens computados em tempo real.",
    status_view_reports: "Ver Histórico Completo por Períodos →",
    status_play_title: "Playground de Teste do Modelo",
    status_play_desc: "Valide imediatamente as respostas do modelo ativo, latência e comportamento sob o prompt Orion.",
    status_test_btn: "Testar Modelo Agora →",
    status_providers_title: "Provedores de Inferência",
    status_cpu_label: "CPU do Host",
    status_ram_label: "Memória RAM",
    status_disk_label: "Armazenamento",
    status_llm_label: "Processo llama-server",

    // Chat Tab
    chat_title: "Playground de Teste",
    chat_subtitle: "Verifique respostas, latência (TTFT) e tokens gerados em streaming direto.",
    chat_provider_label: "Provedor",
    chat_web_search: "Busca Web",
    chat_rag: "RAG Docs",
    chat_clear: "Limpar Chat",
    chat_quick_tests: "Testes rápidos:",
    chat_quick_identity: "✨ Identidade Orion",
    chat_quick_integration: "🏥 Integração Backend / EHR",
    chat_quick_reasoning: "🧠 Raciocínio Clínico",
    chat_quick_throughput: "⚡ Teste de Throughput",
    chat_input_ph: "Digite sua mensagem... (Enter para enviar, Shift+Enter para quebra de linha)",
    chat_attach_title: "Anexar arquivo (PDF, TXT, Imagem)",
    chat_disclaimer: "Orion Light opera com isolamento de contexto e segurança soberana.",
    chat_copy: "Copiar",
    chat_copied: "Copiado!",

    // Models Tab
    models_title: "Central de Modelos",
    models_subtitle: "Pesquise no Hugging Face, baixe quantizações GGUF e ative o modelo de inferência local.",
    models_tab_local: "Modelos Locais em Disco",
    models_tab_hf: "Buscar no Hugging Face",
    models_tab_downloads: "Downloads Ativos",
    models_active_title: "Modelo Ativo Atualmente",
    models_search_ph: "Buscar modelos GGUF (ex: Qwen2.5, Llama-3, DeepSeek, Mistral)...",
    models_search_btn: "Pesquisar",
    models_th_name: "Modelo",
    models_th_size: "Tamanho",
    models_th_status: "Status",
    models_th_actions: "Ações",
    models_btn_activate: "Ativar Modelo",
    models_btn_active: "Ativo",
    models_btn_delete: "Excluir",
    models_btn_download: "Baixar GGUF",
    models_btn_config: "⚙️ Parâmetros",

    // Reports Tab
    reports_title: "Relatórios & Telemetria Histórica",
    reports_subtitle: "Auditoria de requisições, tempo de resposta, latência de primeiro token (TTFT) e consumo de tokens.",
    reports_export_csv: "Exportar CSV",
    reports_range_today: "Hoje",
    reports_range_7d: "Últimos 7 dias",
    reports_range_30d: "Últimos 30 dias",
    reports_range_all: "Todo o período",
    reports_th_time: "Horário",
    reports_th_model: "Modelo / Provedor",
    reports_th_tokens: "Tokens",
    reports_th_ttft: "TTFT (Latência)",
    reports_th_duration: "Duração Total",
    reports_th_speed: "Velocidade",
    reports_th_status: "Status",

    // Users Tab
    users_title: "Usuários & Chaves de API",
    users_subtitle: "Gerencie usuários, operadores ou chaves de integração backend (sistemas externos/EHR).",
    users_btn_new: "+ Novo Usuário",
    users_th_user: "Usuário",
    users_th_role: "Perfil",
    users_th_apikey: "API Key",
    users_th_created: "Criado em",
    users_th_actions: "Ações",

    // Settings Tab
    settings_title: "Configurações do Sistema",
    settings_subtitle: "Ajuste os parâmetros do servidor, provedor padrão e chaves de API externas.",
    settings_btn_save: "Salvar Configurações",
    settings_grp_runtime: "Parâmetros do Runtime & Gateway",
    settings_grp_providers: "Chaves de API & Modelos de Provedores",

    // Modals
    modal_apikey_title: "Chave de Integração (API Key)",
    modal_apikey_warn: "⚠️ Copie agora — esta chave não será exibida novamente.",
    modal_apikey_hint: "Adicione o header Authorization: Bearer <chave> nas integrações com seus sistemas externos ou backend.",
    modal_copy_key: "Copiar Chave",
    modal_close: "Fechar",
    modal_cancel: "Cancelar",
    modal_save: "Salvar",
  },

  en: {
    // Brand & Header
    brand_sub: "Sovereign AI Platform & Model Gateway",
    nav_status: "System Status",
    nav_chat: "Test Playground",
    nav_models: "Model Hub",
    nav_reports: "Reports & Metrics",
    nav_users: "Users & API",
    nav_settings: "Settings",
    btn_logout: "Sign Out",
    slots_active: "active slots",
    realtime_badge: "REAL-TIME",
    btn_pause: "⏸️ Pause",
    btn_resume: "▶️ Resume",

    // Login
    login_subtitle: "Sovereign AI Platform & Model Gateway",
    login_user_label: "Username",
    login_user_ph: "admin",
    login_pass_label: "Password",
    login_pass_ph: "••••••••",
    login_btn: "Sign In",
    login_err_default: "Invalid credentials",
    login_err_net: "Server connection error",

    // Status Tab
    status_title: "Telemetry & Status",
    status_subtitle: "Gateway health overview, host hardware resources, and real-time inference throughput.",
    status_hw_title: "Hardware Resources & LLM Process",
    status_hw_subtitle: "Metrics polled every 2s directly from the host and native runtime.",
    status_throughput_title: "Throughput & Performance (Real-Time / Today)",
    status_throughput_subtitle: "Success rate, latency, and token consumption computed in real time.",
    status_view_reports: "View Full Period History →",
    status_play_title: "Model Test Playground",
    status_play_desc: "Immediately validate active model responses, latency, and behavior under the Orion prompt.",
    status_test_btn: "Test Model Now →",
    status_providers_title: "Inference Providers",
    status_cpu_label: "Host CPU",
    status_ram_label: "RAM Memory",
    status_disk_label: "Storage",
    status_llm_label: "llama-server Process",

    // Chat Tab
    chat_title: "Test Playground",
    chat_subtitle: "Inspect stream responses, latency (TTFT), and generated tokens in direct streaming.",
    chat_provider_label: "Provider",
    chat_web_search: "Web Search",
    chat_rag: "RAG Docs",
    chat_clear: "Clear Chat",
    chat_quick_tests: "Quick tests:",
    chat_quick_identity: "✨ Orion Identity",
    chat_quick_integration: "🏥 Backend / EHR Integration",
    chat_quick_reasoning: "🧠 Clinical Reasoning",
    chat_quick_throughput: "⚡ Throughput Test",
    chat_input_ph: "Type your message... (Enter to send, Shift+Enter for newline)",
    chat_attach_title: "Attach file (PDF, TXT, Image)",
    chat_disclaimer: "Orion Light operates with strict context isolation and sovereign privacy.",
    chat_copy: "Copy",
    chat_copied: "Copied!",

    // Models Tab
    models_title: "Model Hub",
    models_subtitle: "Search Hugging Face, download GGUF quantizations, and activate local inference models.",
    models_tab_local: "Local Models on Disk",
    models_tab_hf: "Search on Hugging Face",
    models_tab_downloads: "Active Downloads",
    models_active_title: "Currently Active Model",
    models_search_ph: "Search GGUF models (e.g., Qwen2.5, Llama-3, DeepSeek, Mistral)...",
    models_search_btn: "Search",
    models_th_name: "Model",
    models_th_size: "Size",
    models_th_status: "Status",
    models_th_actions: "Actions",
    models_btn_activate: "Activate Model",
    models_btn_active: "Active",
    models_btn_delete: "Delete",
    models_btn_download: "Download GGUF",
    models_btn_config: "⚙️ Parameters",

    // Reports Tab
    reports_title: "Reports & Historical Telemetry",
    reports_subtitle: "Request audit logs, response times, time-to-first-token (TTFT), and token consumption.",
    reports_export_csv: "Export CSV",
    reports_range_today: "Today",
    reports_range_7d: "Last 7 days",
    reports_range_30d: "Last 30 days",
    reports_range_all: "All time",
    reports_th_time: "Timestamp",
    reports_th_model: "Model / Provider",
    reports_th_tokens: "Tokens",
    reports_th_ttft: "TTFT (Latency)",
    reports_th_duration: "Total Duration",
    reports_th_speed: "Speed",
    reports_th_status: "Status",

    // Users Tab
    users_title: "Users & API Keys",
    users_subtitle: "Manage users, operators, or backend integration keys (external systems/EHR).",
    users_btn_new: "+ New User",
    users_th_user: "User",
    users_th_role: "Role",
    users_th_apikey: "API Key",
    users_th_created: "Created At",
    users_th_actions: "Actions",

    // Settings Tab
    settings_title: "System Settings",
    settings_subtitle: "Tune server parameters, default provider, and external API credentials.",
    settings_btn_save: "Save Settings",
    settings_grp_runtime: "Runtime & Gateway Parameters",
    settings_grp_providers: "API Keys & Provider Models",

    // Modals
    modal_apikey_title: "Integration Key (API Key)",
    modal_apikey_warn: "⚠️ Copy now — this key will never be displayed again.",
    modal_apikey_hint: "Add header Authorization: Bearer <key> in your external backend or service requests.",
    modal_copy_key: "Copy Key",
    modal_close: "Close",
    modal_cancel: "Cancel",
    modal_save: "Save",
  },

  es: {
    // Brand & Header
    brand_sub: "Plataforma Soberana de IA & Gateway de Modelos",
    nav_status: "Estado General",
    nav_chat: "Playground de Prueba",
    nav_models: "Gestión de Modelos",
    nav_reports: "Informes y Métricas",
    nav_users: "Usuarios y API",
    nav_settings: "Configuraciones",
    btn_logout: "Cerrar Sesión",
    slots_active: "slots activos",
    realtime_badge: "TIEMPO REAL",
    btn_pause: "⏸️ Pausar",
    btn_resume: "▶️ Reanudar",

    // Login
    login_subtitle: "Plataforma de Inteligencia & Gateway de Modelos",
    login_user_label: "Usuario",
    login_user_ph: "admin",
    login_pass_label: "Contraseña",
    login_pass_ph: "••••••••",
    login_btn: "Autenticar",
    login_err_default: "Credenciales inválidas",
    login_err_net: "Error de conexión con el servidor",

    // Status Tab
    status_title: "Telemetría y Estado",
    status_subtitle: "Visión general del gateway, recursos de hardware y throughput de inferencia en tiempo real.",
    status_hw_title: "Recursos de Hardware y Proceso LLM",
    status_hw_subtitle: "Métricas obtenidas cada 2s directamente del host y proceso nativo.",
    status_throughput_title: "Throughput y Rendimiento (Tiempo Real / Hoy)",
    status_throughput_subtitle: "Tasa de éxito, latencia y consumo de tokens computados en tiempo real.",
    status_view_reports: "Ver Historial Completo por Períodos →",
    status_play_title: "Playground de Prueba del Modelo",
    status_play_desc: "Valide de inmediato las respuestas del modelo activo, latencia y comportamiento bajo el prompt Orion.",
    status_test_btn: "Probar Modelo Ahora →",
    status_providers_title: "Proveedores de Inferencia",
    status_cpu_label: "CPU del Host",
    status_ram_label: "Memoria RAM",
    status_disk_label: "Almacenamiento",
    status_llm_label: "Proceso llama-server",

    // Chat Tab
    chat_title: "Playground de Prueba",
    chat_subtitle: "Verifique respuestas, latencia (TTFT) y tokens generados en streaming directo.",
    chat_provider_label: "Proveedor",
    chat_web_search: "Búsqueda Web",
    chat_rag: "Docs RAG",
    chat_clear: "Limpiar Chat",
    chat_quick_tests: "Pruebas rápidas:",
    chat_quick_identity: "✨ Identidad Orion",
    chat_quick_integration: "🏥 Integración Backend / EHR",
    chat_quick_reasoning: "🧠 Razonamiento Clínico",
    chat_quick_throughput: "⚡ Prueba de Throughput",
    chat_input_ph: "Escriba su mensaje... (Enter para enviar, Shift+Enter para salto de línea)",
    chat_attach_title: "Adjuntar archivo (PDF, TXT, Imagen)",
    chat_disclaimer: "Orion Light opera con aislamiento de contexto y seguridad soberana.",
    chat_copy: "Copiar",
    chat_copied: "¡Copiado!",

    // Models Tab
    models_title: "Central de Modelos",
    models_subtitle: "Busque en Hugging Face, descargue cuantizaciones GGUF y active el modelo de inferencia local.",
    models_tab_local: "Modelos Locales en Disco",
    models_tab_hf: "Buscar en Hugging Face",
    models_tab_downloads: "Descargas Activas",
    models_active_title: "Modelo Activo Actualmente",
    models_search_ph: "Buscar modelos GGUF (ej: Qwen2.5, Llama-3, DeepSeek, Mistral)...",
    models_search_btn: "Buscar",
    models_th_name: "Modelo",
    models_th_size: "Tamaño",
    models_th_status: "Estado",
    models_th_actions: "Acciones",
    models_btn_activate: "Activar Modelo",
    models_btn_active: "Activo",
    models_btn_delete: "Eliminar",
    models_btn_download: "Descargar GGUF",
    models_btn_config: "⚙️ Parámetros",

    // Reports Tab
    reports_title: "Informes y Telemetría Histórica",
    reports_subtitle: "Auditoría de peticiones, tiempo de respuesta, latencia del primer token (TTFT) y consumo de tokens.",
    reports_export_csv: "Exportar CSV",
    reports_range_today: "Hoy",
    reports_range_7d: "Últimos 7 días",
    reports_range_30d: "Últimos 30 días",
    reports_range_all: "Todo el período",
    reports_th_time: "Horario",
    reports_th_model: "Modelo / Proveedor",
    reports_th_tokens: "Tokens",
    reports_th_ttft: "TTFT (Latencia)",
    reports_th_duration: "Duración Total",
    reports_th_speed: "Velocidad",
    reports_th_status: "Estado",

    // Users Tab
    users_title: "Usuarios y Claves de API",
    users_subtitle: "Gestione usuarios, operadores o claves de integración backend (sistemas externos/EHR).",
    users_btn_new: "+ Nuevo Usuario",
    users_th_user: "Usuario",
    users_th_role: "Perfil",
    users_th_apikey: "Clave de API",
    users_th_created: "Creado en",
    users_th_actions: "Acciones",

    // Settings Tab
    settings_title: "Configuraciones del Sistema",
    settings_subtitle: "Ajuste los parámetros del servidor, proveedor predeterminado y credenciales externas.",
    settings_btn_save: "Guardar Configuraciones",
    settings_grp_runtime: "Parámetros de Runtime y Gateway",
    settings_grp_providers: "Claves de API y Modelos de Proveedores",

    // Modals
    modal_apikey_title: "Clave de Integración (API Key)",
    modal_apikey_warn: "⚠️ Copie ahora — esta clave no se volverá a mostrar.",
    modal_apikey_hint: "Agregue el encabezado Authorization: Bearer <clave> en las integraciones con su backend o sistemas externos.",
    modal_copy_key: "Copiar Clave",
    modal_close: "Cerrar",
    modal_cancel: "Cancelar",
    modal_save: "Guardar",
  }
};

let _currentLang = localStorage.getItem('orion_light_lang') || 'pt';

function t(key, fallback = '') {
  const dict = ORION_TRANSLATIONS[_currentLang] || ORION_TRANSLATIONS['pt'];
  return dict[key] !== undefined ? dict[key] : (fallback || key);
}

function setLanguage(lang) {
  if (!['pt', 'en', 'es'].includes(lang)) lang = 'pt';
  _currentLang = lang;
  localStorage.setItem('orion_light_lang', lang);

  // Update UI active markers
  ['pt', 'en', 'es'].forEach(function(l) {
    document.querySelectorAll('.btn-lang-' + l).forEach(function(el) {
      if (l === lang) {
        el.classList.add('bg-cyan-500/20', 'text-cyan-300', 'border-cyan-500/40');
        el.classList.remove('text-slate-400', 'border-transparent');
      } else {
        el.classList.remove('bg-cyan-500/20', 'text-cyan-300', 'border-cyan-500/40');
        el.classList.add('text-slate-400', 'border-transparent');
      }
    });
  });

  // Apply translations to data-i18n elements
  document.querySelectorAll('[data-i18n]').forEach(function(el) {
    const k = el.getAttribute('data-i18n');
    const val = t(k);
    if (val) el.textContent = val;
  });

  // Apply translations to placeholders
  document.querySelectorAll('[data-i18n-ph]').forEach(function(el) {
    const k = el.getAttribute('data-i18n-ph');
    const val = t(k);
    if (val) el.setAttribute('placeholder', val);
  });

  // Apply translations to titles
  document.querySelectorAll('[data-i18n-title]').forEach(function(el) {
    const k = el.getAttribute('data-i18n-title');
    const val = t(k);
    if (val) el.setAttribute('title', val);
  });

  // Refresh active section if available
  if (typeof _currentSection !== 'undefined') {
    if (_currentSection === 'status' && typeof loadStatus === 'function') loadStatus();
    if (_currentSection === 'models' && typeof loadModels === 'function') loadModels();
    if (_currentSection === 'reports' && typeof loadReports === 'function') loadReports();
    if (_currentSection === 'users' && typeof loadUsers === 'function') loadUsers();
    if (_currentSection === 'settings' && typeof loadSettings === 'function') loadSettings();
  }
}

// Auto-run on DOM ready
if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', function() {
    setLanguage(_currentLang);
  });
}
