import express from 'express';
import { createServer } from 'http';
import { Server } from 'socket.io';
import cors from 'cors';
import purchasesRouter from './routes/purchases.js';
import { startPricePoller, getLatestPrice } from './services/pricePoller.js';
import { startBlockPoller, getLatestBlocks } from './services/blockPoller.js';

const app = express();
const httpServer = createServer(app);
const io = new Server(httpServer, {
  cors: {
    origin: ['http://localhost:5173', 'http://127.0.0.1:5173'],
    methods: ['GET', 'POST'],
  },
});

app.use(cors());
app.use(express.json());

// API routes
app.use('/api/purchases', purchasesRouter);

app.get('/api/price', (req, res) => {
  res.json(getLatestPrice());
});

app.get('/api/blocks', (req, res) => {
  res.json(getLatestBlocks());
});

// WebSocket
io.on('connection', (socket) => {
  console.log('Client connected:', socket.id);

  // Send current price immediately to new clients
  const current = getLatestPrice();
  if (current.price !== null) {
    socket.emit('priceUpdate', current);
  }

  // Send current blocks immediately to new clients
  const blocks = getLatestBlocks();
  if (blocks.length > 0) {
    socket.emit('blocksUpdate', blocks);
  }

  socket.on('disconnect', () => {
    console.log('Client disconnected:', socket.id);
  });
});

// Start pollers
startPricePoller(io);
startBlockPoller(io);

const PORT = process.env.PORT || 3001;
httpServer.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
});
