# Bitcoin Purchase Tracker

A real-time Bitcoin purchase tracking app that monitors your BTC investments with live price updates.

## Features

- **Real-time BTC price** via CoinGecko API (updates every 30s)
- **Track purchases** with date, BTC amount, and purchase price
- **Live portfolio dashboard** showing total invested, current value, and profit/loss
- **Per-purchase P/L** with percentage calculations
- **Dark theme** financial dashboard UI
- **Persistent storage** with SQLite

## Tech Stack

- **Frontend:** React 18 + Vite
- **Backend:** Node.js + Express + socket.io
- **Database:** SQLite (better-sqlite3)
- **Price Feed:** CoinGecko API + WebSocket push

## Quick Start

```bash
# Install all dependencies
npm run install:all

# Start both server and client
npm run dev
```

- Server runs on `http://localhost:3001`
- Client runs on `http://localhost:5173`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/purchases` | List all purchases |
| POST | `/api/purchases` | Add a purchase |
| DELETE | `/api/purchases/:id` | Delete a purchase |
| GET | `/api/price` | Get current BTC price |
