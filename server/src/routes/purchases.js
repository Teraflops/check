import { Router } from 'express';
import { getAllPurchases, addPurchase, deletePurchase } from '../db.js';

const router = Router();

router.get('/', (req, res) => {
  const purchases = getAllPurchases();
  res.json(purchases);
});

router.post('/', (req, res) => {
  const { date, btc_amount, price_usd } = req.body;

  if (!date || typeof date !== 'string') {
    return res.status(400).json({ error: 'Valid date is required' });
  }
  if (!btc_amount || typeof btc_amount !== 'number' || btc_amount <= 0) {
    return res.status(400).json({ error: 'btc_amount must be a positive number' });
  }
  if (!price_usd || typeof price_usd !== 'number' || price_usd <= 0) {
    return res.status(400).json({ error: 'price_usd must be a positive number' });
  }

  const purchase = addPurchase({ date, btc_amount, price_usd });
  res.status(201).json(purchase);
});

router.delete('/:id', (req, res) => {
  const id = parseInt(req.params.id, 10);
  if (isNaN(id)) {
    return res.status(400).json({ error: 'Invalid ID' });
  }

  const deleted = deletePurchase(id);
  if (!deleted) {
    return res.status(404).json({ error: 'Purchase not found' });
  }
  res.json({ success: true });
});

export default router;
