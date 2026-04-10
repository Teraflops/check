import React, { useState, useEffect, useCallback } from 'react';
import { useSocket } from './hooks/useSocket';
import { getPurchases, addPurchase, deletePurchase } from './api/purchases';
import Dashboard from './components/Dashboard';
import PurchaseForm from './components/PurchaseForm';
import PurchaseList from './components/PurchaseList';

export default function App() {
  const { currentPrice, lastUpdated } = useSocket();
  const [purchases, setPurchases] = useState([]);

  const fetchPurchases = useCallback(async () => {
    try {
      const data = await getPurchases();
      setPurchases(data);
    } catch (err) {
      console.error('Failed to load purchases:', err);
    }
  }, []);

  useEffect(() => {
    fetchPurchases();
  }, [fetchPurchases]);

  async function handleAdd(data) {
    await addPurchase(data);
    await fetchPurchases();
  }

  async function handleDelete(id) {
    await deletePurchase(id);
    await fetchPurchases();
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>₿ Bitcoin Purchase Tracker</h1>
        <span className="live-badge">LIVE</span>
      </header>

      <Dashboard
        purchases={purchases}
        currentPrice={currentPrice}
        lastUpdated={lastUpdated}
      />

      <PurchaseForm currentPrice={currentPrice} onAdd={handleAdd} />

      <PurchaseList
        purchases={purchases}
        currentPrice={currentPrice}
        onDelete={handleDelete}
      />
    </div>
  );
}
