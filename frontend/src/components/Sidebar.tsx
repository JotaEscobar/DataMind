import React, { useState } from 'react';
import { Plus, Sun, Moon, MoreHorizontal, Trash2, Edit2, X } from 'lucide-react';
import { useChatStore } from '../store/useChatStore';
import { cn } from '../lib/utils';
import type { SessionSummary } from '../services/api';

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  sessions: SessionSummary[];
  activeSessionId: string;
  isLoading: boolean;
  pendingSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onCreateSession: () => void;
  onRenameSession: (session: SessionSummary) => void;
  onDeleteSession: (session: SessionSummary) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  isOpen,
  onClose,
  sessions,
  activeSessionId,
  isLoading,
  pendingSessionId,
  onSelectSession,
  onCreateSession,
  onRenameSession,
  onDeleteSession,
}) => {
  const { sessionId, messages } = useChatStore();
  const [isLight, setIsLight] = useState(localStorage.getItem('theme') === 'light');
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);

  const toggleTheme = () => {
    const next = !isLight;
    setIsLight(next);
    document.documentElement.classList.toggle('light-theme', next);
    localStorage.setItem('theme', next ? 'light' : 'dark');
  };

  const toggleMenu = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    setOpenMenuId(prev => prev === id ? null : id);
  };

  // Cierra el menú al hacer clic fuera
  const handleItemClick = (id: string) => {
    setOpenMenuId(null);
    if (pendingSessionId === id) return;
    onSelectSession(id);
    onClose();
  };

  const allSessions = [
    ...sessions,
    // Muestra sesión activa si no está guardada aún
    ...(!sessions.some(s => s.session_id === sessionId) && messages.length > 0
      ? [{ session_id: sessionId, title: 'Conversación actual' }]
      : [])
  ];

  return (
    <aside className={cn('sidebar', isOpen && 'is-open')}>

      {/* ── Franja de acento lateral ── */}
      <div className="sidebar-stripe" />

      {/* ── Brand ── */}
      <div className="sb-brand">
        <div className="sb-brand-avatar">
          <img src="/icono.png" alt="DataMind" />
        </div>
        <div className="sb-brand-info">
          <div className="sb-brand-name">Data<span>Mind</span></div>
          <div className="sb-brand-author">By Jorge Escobar</div>
        </div>
        <div className="sb-badge">BETA</div>
        <button
          type="button"
          onClick={onClose}
          className="sb-close-btn lg:hidden"
          aria-label="Cerrar"
        >
          <X size={13} />
        </button>
      </div>

      {/* ── Nueva conversación ── */}
      <button
        onClick={() => { onCreateSession(); onClose(); }}
        className="new-chat-btn"
      >
        <Plus size={14} strokeWidth={2.5} />
        <span>Nueva conversación</span>
      </button>

      {/* ── Historial ── */}
      <div className="history-section custom-scrollbar">
        <div className="history-group-label">Sesiones Recientes</div>

        {/* Skeleton de carga */}
        {isLoading && allSessions.length === 0 && (
          <div className="sb-skeleton-wrap">
            {[1, 2, 3].map(i => (
              <div key={i} className="sb-skeleton" />
            ))}
          </div>
        )}

        {/* Vacío */}
        {!isLoading && allSessions.length === 0 && (
          <div className="sb-empty">No hay chats guardados.</div>
        )}

        {/* Items */}
        {allSessions.map(session => {
          const isActive = session.session_id === activeSessionId;
          const isPending = pendingSessionId === session.session_id;
          const menuOpen = openMenuId === session.session_id;

          return (
            <div
              key={session.session_id}
              className={cn('history-item group', isActive && 'active', isPending && 'opacity-50 pointer-events-none')}
              onClick={() => handleItemClick(session.session_id)}
            >
              <div className="hi-row">
                <span className="hi-title">{session.title}</span>

                {/* Botón ··· */}
                <button
                  type="button"
                  onClick={e => toggleMenu(e, session.session_id)}
                  className="hi-menu-btn"
                  aria-label="Opciones"
                >
                  <MoreHorizontal size={13} />
                </button>
              </div>

              <div className="hi-meta">
                {isPending ? 'Cargando...' : `ID: ${session.session_id.slice(-6)}`}
              </div>

              {/* Menú contextual */}
              {menuOpen && (
                <div
                  className="hi-ctx-menu"
                  onClick={e => e.stopPropagation()}
                >
                  <button
                    className="hi-ctx-item"
                    onClick={() => { setOpenMenuId(null); onRenameSession(session); }}
                  >
                    <Edit2 size={11} /> Renombrar
                  </button>
                  <button
                    className="hi-ctx-item danger"
                    onClick={() => { setOpenMenuId(null); onDeleteSession(session); }}
                  >
                    <Trash2 size={11} /> Eliminar
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Perfil de usuario ── */}
      <div className="sb-user">
        <div className="sb-user-avatar">JE</div>
        <div className="sb-user-info">
          <div className="sb-user-name">Jorge Escobar</div>
          <div className="sb-user-role">analyst · local</div>
        </div>
        <button
          onClick={toggleTheme}
          className="sb-theme-btn"
          title={isLight ? 'Modo oscuro' : 'Modo claro'}
        >
          {isLight ? <Moon size={14} /> : <Sun size={14} />}
        </button>
      </div>

    </aside>
  );
};