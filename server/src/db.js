import Database from 'better-sqlite3';
import { mkdirSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const dataDir = join(__dirname, '..', 'data');
mkdirSync(dataDir, { recursive: true });

const db = new Database(join(dataDir, 'tracker.db'));

// Enable WAL mode for better concurrent read performance
db.pragma('journal_mode = WAL');

db.exec(`
  CREATE TABLE IF NOT EXISTS purchases (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT    NOT NULL,
    btc_amount REAL    NOT NULL,
    price_usd  REAL    NOT NULL,
    total_cost REAL    NOT NULL,
    created_at TEXT    DEFAULT (datetime('now'))
  )
`);

const stmts = {
  getAll: db.prepare('SELECT * FROM purchases ORDER BY date DESC, id DESC'),
  insert: db.prepare(
    'INSERT INTO purchases (date, btc_amount, price_usd, total_cost) VALUES (?, ?, ?, ?)'
  ),
  delete: db.prepare('DELETE FROM purchases WHERE id = ?'),
};

export function getAllPurchases() {
  return stmts.getAll.all();
}

export function addPurchase({ date, btc_amount, price_usd }) {
  const total_cost = btc_amount * price_usd;
  const result = stmts.insert.run(date, btc_amount, price_usd, total_cost);
  return { id: result.lastInsertRowid, date, btc_amount, price_usd, total_cost };
}

export function deletePurchase(id) {
  const result = stmts.delete.run(id);
  return result.changes > 0;
}

export default db;
