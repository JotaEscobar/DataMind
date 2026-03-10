import React from 'react';

const particles = [
  { text: '+12.4%', left: '15%', top: '10%', delay: '0s' },
  { text: '↗ trend', left: '82%', top: '20%', delay: '1s' },
  { text: 'σ=0.87', left: '10%', top: '75%', delay: '2s' },
  { text: 'cluster_3', left: '80%', top: '70%', delay: '1.5s' },
  { text: '∑ 48.2K', left: '5%', top: '40%', delay: '0.5s' },
];

const suggestions = [
  "¿Cuál fue el mes con más ventas?",
  "Muéstrame una torta por categoría",
  "Detecta anomalías en los datos",
  "Tendencia de los últimos 6 meses",
];

export const EmptyState: React.FC<{ onSuggestion: (query: string) => void }> = ({ onSuggestion }) => {
  return (
    <div id="empty-state">
      {/* Cuadrícula de fondo */}
      <div className="empty-grid" />

      {/* Partículas flotantes */}
      {particles.map((p, i) => (
        <div
          key={i}
          className="particle"
          style={{ left: p.left, top: p.top, animationDelay: p.delay }}
        >
          {p.text}
        </div>
      ))}

      {/* Mascot */}
      <div className="mascot-wrap">
        <div className="mascot-glow" />
        <div className="mascot-glow-2" />
        <div className="mascot-ring mascot-ring-1" />
        <div className="mascot-ring mascot-ring-2" />
        <img src="/logo.png" alt="DataMind" className="mascot-img" id="mascot" />
      </div>

      <h2 className="empty-title">
        Hola, soy <span>DataMind</span>
      </h2>
      <p className="empty-subtitle">
        Tu analista de datos con IA. Adjunta un archivo CSV o Excel y pregúntame lo que necesitas.
      </p>

      <div className="suggestion-chips">
        {suggestions.map((s, i) => (
          <button key={i} className="chip" onClick={() => onSuggestion(s)}>
            {s}
          </button>
        ))}
      </div>
    </div>
  );
};