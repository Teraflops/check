import React from 'react';

function formatUSD(value) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

function formatBTC(value) {
  return value.toFixed(8);
}

export default function Dashboard({ purchases, currentPrice, lastUpdated }) {
  const totalBtc = purchases.reduce((sum, p) => sum + p.btc_amount, 0);
  const totalInvested = purchases.reduce((sum, p) => sum + p.total_cost, 0);
  const currentValue = currentPrice ? totalBtc * currentPrice : 0;
  const profitLoss = currentValue - totalInvested;
  const profitLossPct = totalInvested > 0 ? (profitLoss / totalInvested) * 100 : 0;

  const plClass = profitLoss >= 0 ? 'profit' : 'loss';
  const timeStr = lastUpdated
    ? new Date(lastUpdated).toLocaleTimeString()
    : '—';

  return (
    <div className="dashboard">
      <div className="stat-card highlight">
        <span className="stat-label">BTC Price</span>
        <span className="stat-value">
          {currentPrice ? formatUSD(currentPrice) : 'Loading...'}
        </span>
        <span className="stat-sub">Updated: {timeStr}</span>
      </div>

      <div className="stat-card">
        <span className="stat-label">Total BTC Held</span>
        <span className="stat-value">{formatBTC(totalBtc)}</span>
      </div>

      <div className="stat-card">
        <span className="stat-label">Total Invested</span>
        <span className="stat-value">{formatUSD(totalInvested)}</span>
      </div>

      <div className="stat-card">
        <span className="stat-label">Portfolio Value</span>
        <span className="stat-value">
          {currentPrice ? formatUSD(currentValue) : '—'}
        </span>
      </div>

      <div className={`stat-card ${plClass}`}>
        <span className="stat-label">Profit / Loss</span>
        <span className="stat-value">
          {currentPrice ? formatUSD(profitLoss) : '—'}
        </span>
        <span className="stat-sub">
          {currentPrice ? `${profitLossPct >= 0 ? '+' : ''}${profitLossPct.toFixed(2)}%` : ''}
        </span>
      </div>
    </div>
  );
}
