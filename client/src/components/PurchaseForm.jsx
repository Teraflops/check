import React, { useState } from 'react';

export default function PurchaseForm({ currentPrice, onAdd }) {
  const today = new Date().toISOString().split('T')[0];
  const [date, setDate] = useState(today);
  const [btcAmount, setBtcAmount] = useState('');
  const [priceUsd, setPriceUsd] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  function handleUseCurrentPrice() {
    if (currentPrice) {
      setPriceUsd(currentPrice.toString());
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');

    const amount = parseFloat(btcAmount);
    const price = parseFloat(priceUsd);

    if (!date) return setError('Date is required');
    if (isNaN(amount) || amount <= 0) return setError('Enter a valid BTC amount');
    if (isNaN(price) || price <= 0) return setError('Enter a valid price');

    setLoading(true);
    try {
      await onAdd({ date, btc_amount: amount, price_usd: price });
      setBtcAmount('');
      setPriceUsd('');
      setDate(today);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form className="purchase-form" onSubmit={handleSubmit}>
      <h2>Add Purchase</h2>
      <div className="form-row">
        <div className="form-group">
          <label htmlFor="date">Date</label>
          <input
            id="date"
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </div>
        <div className="form-group">
          <label htmlFor="btcAmount">BTC Amount</label>
          <input
            id="btcAmount"
            type="number"
            step="0.00000001"
            min="0"
            placeholder="0.00000000"
            value={btcAmount}
            onChange={(e) => setBtcAmount(e.target.value)}
          />
        </div>
        <div className="form-group">
          <label htmlFor="priceUsd">
            Price per BTC (USD)
            {currentPrice && (
              <button
                type="button"
                className="btn-link"
                onClick={handleUseCurrentPrice}
              >
                Use current
              </button>
            )}
          </label>
          <input
            id="priceUsd"
            type="number"
            step="0.01"
            min="0"
            placeholder="0.00"
            value={priceUsd}
            onChange={(e) => setPriceUsd(e.target.value)}
          />
        </div>
        <div className="form-group form-action">
          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? 'Adding...' : 'Add Purchase'}
          </button>
        </div>
      </div>
      {error && <p className="form-error">{error}</p>}
    </form>
  );
}
