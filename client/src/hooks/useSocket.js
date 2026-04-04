import { useEffect, useState } from 'react';
import { io } from 'socket.io-client';

export function useSocket() {
  const [currentPrice, setCurrentPrice] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  useEffect(() => {
    const socket = io('http://localhost:3001');

    socket.on('priceUpdate', (data) => {
      setCurrentPrice(data.price);
      setLastUpdated(data.lastUpdated);
    });

    return () => socket.disconnect();
  }, []);

  return { currentPrice, lastUpdated };
}
