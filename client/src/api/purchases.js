export async function getPurchases() {
  const res = await fetch('/api/purchases');
  if (!res.ok) throw new Error('Failed to fetch purchases');
  return res.json();
}

export async function addPurchase({ date, btc_amount, price_usd }) {
  const res = await fetch('/api/purchases', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date, btc_amount, price_usd }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.error || 'Failed to add purchase');
  }
  return res.json();
}

export async function deletePurchase(id) {
  const res = await fetch(`/api/purchases/${id}`, { method: 'DELETE' });
  if (!res.ok) throw new Error('Failed to delete purchase');
  return res.json();
}

export async function getCurrentPrice() {
  const res = await fetch('/api/price');
  if (!res.ok) throw new Error('Failed to fetch price');
  return res.json();
}
