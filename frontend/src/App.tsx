import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Download,
  RotateCcw,
  PanelLeft,
  AlertCircle,
  CheckCircle2,
  Loader2,
  X,
  FileText,
  Presentation,
  LayoutDashboard,
} from 'lucide-react';
import { useChatStore } from './store/useChatStore';
import type { Message } from './store/useChatStore';
import { Sidebar } from './components/Sidebar';
import { ChatMessage } from './components/ChatMessage';
import { EmptyState } from './components/EmptyState';
import { InputZone } from './components/InputZone';
import {
  streamAnalysis,
  fetchSessions,
  fetchSessionHistory,
  renameSession,
  deleteSession,
  exportData,
  type SessionSummary,
} from './services/api';

function App() {
  const {
    messages,
    addMessage,
    updateLastMessage,
    clearMessages,
    isLoading,
    setIsLoading,
    sessionId,
    setSessionId,
    setMessagesFromHistory,
  } = useChatStore();

  const [model, setModel] = useState('groq/llama-3.3-70b-versatile');
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [isSessionsLoading, setIsSessionsLoading] = useState(true);
  const [isSessionSwitching, setIsSessionSwitching] = useState(false);
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ type: 'error' | 'success'; message: string } | null>(null);

  // ── Estado del menú de exportación ──────────────────────────────────────────
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const exportMenuRef = useRef<HTMLDivElement>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const showNotice = (type: 'error' | 'success', message: string) => {
    setNotice({ type, message });
  };

  const loadSessions = useCallback(async (options?: { silent?: boolean }) => {
    const silent = options?.silent ?? false;

    if (!silent) {
      setIsSessionsLoading(true);
    }

    try {
      const data = await fetchSessions();
      setSessions(data);
    } catch {
      if (!silent) {
        showNotice('error', 'No se pudieron cargar las sesiones guardadas.');
      }
    } finally {
      if (!silent) {
        setIsSessionsLoading(false);
      }
    }
  }, []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4200);
    return () => window.clearTimeout(timer);
  }, [notice]);

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth >= 1024) setIsSidebarOpen(false);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Cerrar menú de exportación al hacer click fuera
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(e.target as Node)) {
        setShowExportMenu(false);
      }
    };
    if (showExportMenu) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showExportMenu]);

  const upsertSession = (session: SessionSummary) => {
    setSessions((prev) => {
      const without = prev.filter((item) => item.session_id !== session.session_id);
      return [session, ...without];
    });
  };

  const handleCreateSession = () => {
    clearMessages();
    setIsSidebarOpen(false);
  };

  const handleSelectSession = async (selectedSessionId: string) => {
    if (selectedSessionId === sessionId) return;

    setPendingSessionId(selectedSessionId);
    setIsSessionSwitching(true);
    setIsLoading(true);

    try {
      const history = await fetchSessionHistory(selectedSessionId);
      setSessionId(selectedSessionId);
      setMessagesFromHistory(history);
      setIsSidebarOpen(false);
    } catch {
      showNotice('error', 'No se pudo cargar el historial de la sesión seleccionada.');
    } finally {
      setIsSessionSwitching(false);
      setPendingSessionId(null);
      setIsLoading(false);
    }
  };

  const handleRenameSession = async (session: SessionSummary) => {
    const currentTitle = session.title.trim();
    const nextTitle = prompt('Nuevo nombre de la sesión:', currentTitle);

    if (!nextTitle) return;
    const normalizedTitle = nextTitle.trim();
    if (!normalizedTitle || normalizedTitle === currentTitle) return;

    try {
      await renameSession(session.session_id, normalizedTitle);
      upsertSession({ ...session, title: normalizedTitle });
      showNotice('success', 'Sesión renombrada correctamente.');
    } catch {
      showNotice('error', 'No se pudo renombrar la sesión.');
    }
  };

  const handleDeleteSession = async (session: SessionSummary) => {
    const confirmed = confirm(`¿Eliminar la sesión "${session.title}"? Esta acción no se puede deshacer.`);
    if (!confirmed) return;

    try {
      await deleteSession(session.session_id);
      setSessions((prev) => prev.filter((item) => item.session_id !== session.session_id));
      if (session.session_id === sessionId) clearMessages();
      showNotice('success', 'Sesión eliminada.');
    } catch {
      showNotice('error', 'No se pudo eliminar la sesión.');
    }
  };

  // ── Exportación ──────────────────────────────────────────────────────────────
  const handleExport = async (type: 'pdf' | 'pptx' | 'dashboard') => {
    setShowExportMenu(false);

    const hasFile = messages.some(
      (m) => m.role === 'user' && m.content.startsWith('📎')
    ) || messages.length > 0;

    if (!hasFile) {
      showNotice('error', 'Debes cargar un archivo antes de exportar.');
      return;
    }

    setIsExporting(true);
    showNotice('success', `Generando ${type.toUpperCase()}…`);

    const activeSession = sessions.find((s) => s.session_id === sessionId);
    const title = activeSession?.title || 'Análisis DataMind';
    const insights = messages
      .filter((m) => m.role === 'assistant' && m.content)
      .map((m) => m.content)
      .join('\n\n');

    try {
      await exportData(type, sessionId, title, insights);
      showNotice('success', `${type.toUpperCase()} generado correctamente.`);
    } catch (err) {
      console.error('Export error:', err);
      showNotice('error', `Error al generar el ${type.toUpperCase()}. ¿Hay datos cargados?`);
    } finally {
      setIsExporting(false);
    }
  };

  const activeSession = sessions.find((session) => session.session_id === sessionId);

  const handleSendMessage = async (content: string, file?: File) => {
    const userMsg = content.trim() || (file ? `📎 Adjunto: ${file.name}` : '');
    addMessage({ role: 'user', content: userMsg });

    setIsLoading(true);

    addMessage({
      role: 'assistant',
      content: '',
      isStreaming: true,
      thoughts: [],
      chartImages: [],
    });

    const question = content.trim() || (file
      ? 'Analiza este archivo y dame un resumen del dataset.'
      : '¿Qué puedes decirme sobre los datos actuales?');

    try {
      await streamAnalysis(
        question,
        file || undefined,
        model,
        sessionId,
        (chunk) => {
          if (chunk.type === 'thought') {
            updateLastMessage((msg: Message) => ({
              ...msg,
              thoughts: [...(msg.thoughts ?? []), chunk.content]
            }));
          } else if (chunk.type === 'session_title') {
            upsertSession({
              session_id: sessionId,
              title: chunk.title,
            });
          } else if (chunk.type === 'insight_token') {
            updateLastMessage((msg: Message) => ({
              ...msg,
              content: msg.content + chunk.token
            }));
          } else if (chunk.type === 'action') {
            updateLastMessage({ action: chunk.tool });
          } else if (chunk.type === 'chart_image') {
            // ── Acumular imágenes PNG generadas por matplotlib ──
            updateLastMessage((msg: Message) => ({
              ...msg,
              chartImages: [...(msg.chartImages ?? []), chunk.data],
            }));
          } else if (chunk.type === 'done') {
            updateLastMessage({ isStreaming: false });
            loadSessions({ silent: true });
          }
        }
      );
    } catch {
      updateLastMessage({
        content: 'Error al conectar con las neuronas de DataMind. Reintenta.',
        isStreaming: false
      });
      showNotice('error', 'La conexión de streaming falló. Intenta nuevamente.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="app-container">
      <Sidebar
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        sessions={sessions}
        activeSessionId={sessionId}
        isLoading={isSessionsLoading}
        pendingSessionId={pendingSessionId}
        onSelectSession={handleSelectSession}
        onCreateSession={handleCreateSession}
        onRenameSession={handleRenameSession}
        onDeleteSession={handleDeleteSession}
      />
      <button
        type="button"
        aria-label="Cerrar barra lateral"
        className={`sidebar-overlay ${isSidebarOpen ? 'is-visible' : ''}`}
        onClick={() => setIsSidebarOpen(false)}
      />

      <main className="chat-main">
        <header className="topbar">
          <div className="flex items-center gap-3 min-w-0">
            <button
              type="button"
              aria-label="Abrir barra lateral"
              onClick={() => setIsSidebarOpen(true)}
              className="topbar-menu-btn lg:hidden"
            >
              <PanelLeft size={16} />
            </button>
            <div className="topbar-title" id="chat-title">
              {activeSession?.title || (messages.length === 0 ? 'Nueva conversación' : 'DataMind Analysis')}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="topbar-status">
              <span className="status-dot" />
              {isLoading ? 'Procesando' : 'Online'}
            </div>

            {/* ── Botón Exportar con dropdown ── */}
            <div className="export-wrap relative" ref={exportMenuRef}>
              <button
                type="button"
                className="topbar-btn cyan"
                onClick={() => setShowExportMenu((v) => !v)}
                disabled={isExporting}
                title="Exportar análisis"
              >
                {isExporting
                  ? <Loader2 size={12} className="animate-spin" />
                  : <Download size={12} strokeWidth={2.5} />
                }
                Exportar
              </button>

              {showExportMenu && (
                <div
                  style={{
                    position: 'absolute',
                    top: 'calc(100% + 6px)',
                    right: 0,
                    zIndex: 50,
                    background: '#0e1724',
                    border: '1px solid #1a2d42',
                    borderRadius: '10px',
                    padding: '6px',
                    minWidth: '180px',
                    boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
                  }}
                >
                  <button
                    type="button"
                    onClick={() => handleExport('pdf')}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '10px',
                      width: '100%',
                      padding: '9px 12px',
                      borderRadius: '7px',
                      background: 'transparent',
                      border: 'none',
                      color: '#f0f4f8',
                      fontSize: '13px',
                      cursor: 'pointer',
                      textAlign: 'left',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = '#1a2d42')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <FileText size={14} color="#00d4ff" />
                    Reporte PDF
                  </button>

                  <button
                    type="button"
                    onClick={() => handleExport('pptx')}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '10px',
                      width: '100%',
                      padding: '9px 12px',
                      borderRadius: '7px',
                      background: 'transparent',
                      border: 'none',
                      color: '#f0f4f8',
                      fontSize: '13px',
                      cursor: 'pointer',
                      textAlign: 'left',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = '#1a2d42')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <Presentation size={14} color="#a855f7" />
                    PowerPoint
                  </button>

                  <div style={{ height: '1px', background: '#1a2d42', margin: '4px 0' }} />

                  <button
                    type="button"
                    onClick={() => handleExport('dashboard')}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '10px',
                      width: '100%',
                      padding: '9px 12px',
                      borderRadius: '7px',
                      background: 'transparent',
                      border: 'none',
                      color: '#f0f4f8',
                      fontSize: '13px',
                      cursor: 'pointer',
                      textAlign: 'left',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = '#1a2d42')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <LayoutDashboard size={14} color="#00e5a0" />
                    Dashboard interactivo
                  </button>
                </div>
              )}
            </div>

            <button
              onClick={() => {
                if (confirm('¿Resetear la sesión actual?')) clearMessages();
              }}
              className="topbar-btn"
              title="Resetear sesión"
            >
              <RotateCcw size={12} strokeWidth={2.5} />
              Reset
            </button>
          </div>
        </header>

        {notice && (
          <div
            role="status"
            aria-live="polite"
            className={`mx-4 sm:mx-6 mt-3 rounded-xl border px-3 py-2.5 flex items-center gap-2.5 text-[12px] animate-[slideUp_0.2s_ease-out] ${notice.type === 'error'
              ? 'border-red-500/35 bg-red-500/10 text-red-200'
              : 'border-emerald-500/35 bg-emerald-500/10 text-emerald-200'
              }`}
          >
            {notice.type === 'error' ? <AlertCircle size={15} /> : <CheckCircle2 size={15} />}
            <span className="flex-1">{notice.message}</span>
            <button
              type="button"
              onClick={() => setNotice(null)}
              className="p-1 rounded-md hover:bg-black/10 transition-colors"
              aria-label="Cerrar notificación"
            >
              <X size={14} />
            </button>
          </div>
        )}

        <div className="flex-1 overflow-y-auto flex flex-col custom-scrollbar min-h-0">
          {isSessionSwitching ? (
            <div className="flex-1 flex items-center justify-center px-4 sm:px-8">
              <div className="w-full max-w-[980px] py-10">
                <div className="flex items-center gap-3 text-[var(--text-mid)] text-[12px] font-[var(--font-mono)] uppercase tracking-[0.08em] mb-6">
                  <Loader2 size={14} className="animate-spin text-[var(--accent)]" />
                  Cargando historial...
                </div>
                <div className="space-y-3">
                  <div className="h-20 rounded-2xl bg-[var(--surface-base)] border border-[var(--border)] animate-pulse" />
                  <div className="h-14 rounded-2xl bg-[var(--surface-base)] border border-[var(--border)] animate-pulse" />
                  <div className="h-28 rounded-2xl bg-[var(--surface-base)] border border-[var(--border)] animate-pulse" />
                </div>
              </div>
            </div>
          ) : messages.length === 0 ? (
            <EmptyState onSuggestion={(q) => handleSendMessage(q)} />
          ) : (
            <div id="chat-feed">
              {messages.map((msg) => (
                <ChatMessage key={msg.id} message={msg} />
              ))}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        <InputZone
          onSendMessage={handleSendMessage}
          isLoading={isLoading || isSessionSwitching}
          currentModel={model}
          onModelChange={setModel}
        />
      </main>
    </div>
  );
}

export default App;