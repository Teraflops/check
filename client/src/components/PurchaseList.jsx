import React from 'react';

function formatUSD(value) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export default function PurchaseList({ purchases, currentPrice, onDelete }) {
  if (purchases.length === 0) {
    return (
      <div className="purchase-list-empty">
        <p>No purchases yet. Add your first Bitcoin purchase above!</p>
      </div>
    );
  }

  return (
    <div className="purchase-list">
      <h2>Purchase History</h2>
      <div className="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>BTC Amount</th>
              <th>Purchase Price</th>
              <th>Total Cost</th>
              <th>Current Value</th>
              <th>Profit / Loss</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {purchases.map((p) => {
              const currentVal = currentPrice ? p.btc_amount * currentPrice : null;
              const pl = currentVal !== null ? currentVal - p.total_cost : null;
              const plPct =
                pl !== null && p.total_cost > 0
                  ? (pl / p.total_cost) * 100
                  : null;
              const plClass =
                pl !== null ? (pl >= 0 ? 'profit' : 'loss') : '';

              return (
                <tr key={p.id}>
                  <td>{p.date}</td>
                  <td>{p.btc_amount.toFixed(8)}</td>
                  <td>{formatUSD(p.price_usd)}</td>
                  <td>{formatUSD(p.total_cost)}</td>
                  <td>{currentVal !== null ? formatUSD(currentVal) : '—'}</td>
                  <td className={plClass}>
                    {pl !== null ? (
                      <>
                        {formatUSD(pl)}{' '}
                        <span className="pl-pct">
                          ({plPct >= 0 ? '+' : ''}
                          {plPct.toFixed(2)}%)
                        </span>
                      </>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td>
                    <button
                      className="btn-delete"
                      onClick={() => onDelete(p.id)}
                      title="Delete purchase"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
