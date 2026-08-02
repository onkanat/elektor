import React, { useState, useEffect } from 'react';
import type { SystemMetrics } from '../types';

export const SystemMetricsCard: React.FC = () => {
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);

  useEffect(() => {
    const fetchMetrics = () => {
      fetch('/api/system/metrics')
        .then((res) => res.json())
        .then((data) => setMetrics(data))
        .catch((err) => console.error('Error fetching system metrics:', err));
    };

    fetchMetrics();
    const interval = setInterval(fetchMetrics, 5000);
    return () => clearInterval(interval);
  }, []);

  if (!metrics) return null;

  const totalMemGb = (metrics.memory.total_mb / 1024).toFixed(1);
  const usedMemGb = (metrics.memory.used_mb / 1024).toFixed(1);
  const activeModel = metrics.vram_models.length > 0 ? metrics.vram_models[0] : null;

  return (
    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
      {/* CPU Badge */}
      <div className="badge online" style={{ fontSize: '0.75rem', background: 'rgba(56, 189, 248, 0.1)', borderColor: 'rgba(56, 189, 248, 0.3)' }}>
        💻 CPU: <strong style={{ color: '#38bdf8' }}>{metrics.cpu_percent}%</strong>
      </div>

      {/* RAM Badge */}
      <div className="badge online" style={{ fontSize: '0.75rem', background: 'rgba(168, 85, 247, 0.1)', borderColor: 'rgba(168, 85, 247, 0.3)' }}>
        🧠 RAM: <strong style={{ color: '#c084fc' }}>{usedMemGb} / {totalMemGb} GB ({metrics.memory.percent}%)</strong>
      </div>

      {/* VRAM Badge */}
      <div
        className="badge online"
        style={{
          fontSize: '0.75rem',
          background: activeModel ? 'rgba(52, 211, 153, 0.15)' : 'rgba(100, 116, 139, 0.15)',
          borderColor: activeModel ? 'rgba(52, 211, 153, 0.4)' : 'rgba(100, 116, 139, 0.3)',
        }}
      >
        <span className="dot" style={{ background: activeModel ? '#34d399' : '#94a3b8' }}></span>
        🎮 VRAM:{' '}
        {activeModel ? (
          <strong style={{ color: '#34d399' }}>
            {activeModel.name.split(':')[0]} ({activeModel.vram_gb} GB - {activeModel.param_size})
          </strong>
        ) : (
          <span style={{ color: '#94a3b8' }}>Boş (Model Yüklü Değil)</span>
        )}
      </div>
    </div>
  );
};
