import { useEffect, useState } from 'react';
import { io } from 'socket.io-client';

export function useSocket() {
  const [currentPrice, setCurrentPrice] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [blocks, setBlocks] = useState([]);
  const [newBlock, setNewBlock] = useState(null);

  useEffect(() => {
    const socket = io('http://localhost:3001');

    socket.on('priceUpdate', (data) => {
      setCurrentPrice(data.price);
      setLastUpdated(data.lastUpdated);
    });

    socket.on('blocksUpdate', (data) => {
      setBlocks(data);
    });

    socket.on('newBlock', (block) => {
      setNewBlock(block);
      // Clear notification after 10 seconds
      setTimeout(() => setNewBlock(null), 10_000);
    });

    return () => socket.disconnect();
  }, []);

  return { currentPrice, lastUpdated, blocks, newBlock };
}
