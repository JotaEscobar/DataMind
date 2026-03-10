import React, { useState } from 'react';
import { ChevronDown, Brain, Terminal } from 'lucide-react';
import { cn } from '../lib/utils';

interface ThoughtProcessProps {
  thoughts: string[];
  action?: string;
  isStreaming?: boolean;
}

export const ThoughtProcess: React.FC<ThoughtProcessProps> = ({ thoughts, action, isStreaming }) => {
  const [expanded, setExpanded] = useState(false);

  if (thoughts.length === 0 && !action) return null;

  const latestThought = thoughts[thoughts.length - 1];
  const statusLabel = isStreaming ? 'En curso' : 'Completado';
  const title = action
    ? `Ejecutando herramienta: ${action}`
    : latestThought || 'Razonamiento del analista';

  return (
    <div className="mb-4 mt-1 w-full max-w-[720px] bg-[var(--surface-base)] border border-[var(--border)] rounded-[14px] overflow-hidden shadow-[var(--shadow-soft)]">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="w-full text-left px-3.5 py-3 flex items-center gap-3 hover:bg-[var(--surface-elevated)]/60 transition-colors"
      >
        <span className="flex items-center justify-center w-[24px] h-[24px] bg-[var(--accent-dim)] rounded-[7px] text-[var(--accent)] shrink-0">
          <Brain size={12} strokeWidth={2.5} className={cn(isStreaming && 'animate-pulse')} />
        </span>

        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-[var(--font-mono)] uppercase tracking-[0.08em] text-[var(--text-dim)] mb-1">
            Proceso interno
          </div>
          <div className="text-[12px] text-[var(--text-mid)] truncate">
            {title.replace(/\n/g, ' · ')}
          </div>
        </div>

        <span className={cn(
          'text-[9px] uppercase tracking-[0.12em] px-2 py-1 rounded-full border font-semibold',
          isStreaming
            ? 'text-[var(--accent)] border-[var(--accent)]/45 bg-[var(--accent-dim)]'
            : 'text-[var(--text-dim)] border-[var(--border-strong)] bg-[var(--surface-elevated)]'
        )}>
          {statusLabel}
        </span>

        <ChevronDown
          size={14}
          className={cn('text-[var(--text-dim)] transition-transform duration-300 shrink-0', expanded && 'rotate-180')}
        />
      </button>

      <div className={cn(
        'grid transition-all duration-300 ease-out',
        expanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
      )}>
        <div className="overflow-hidden">
          <div className="px-4 pb-4 pt-2 border-t border-[var(--border)] text-[11px] text-[var(--text-mid)] leading-relaxed font-[var(--font-mono)] break-words">
            {thoughts.map((t, i) => (
              <div key={i} className="mb-2.5 pb-2.5 border-b border-[var(--border)] last:border-none last:pb-0 last:mb-0 flex gap-3">
                <span className="text-[var(--text-dim)] shrink-0 opacity-50">{String(i + 1).padStart(2, '0')}</span>
                <span className="flex-1">{t}</span>
              </div>
            ))}

            {action && (
              <div className="text-[var(--accent)] bg-[var(--accent-dim)] p-2.5 rounded-lg mt-3 flex items-center gap-3 border border-[var(--accent)]/30">
                <Terminal size={12} className="shrink-0" />
                <span className="font-semibold flex-1">Herramienta activa: {action}</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
