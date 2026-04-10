const COINGECKO_URL =
  'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd';

let latestPrice = null;
let lastUpdated = null;

export function getLatestPrice() {
  return { price: latestPrice, lastUpdated };
}

async function fetchPrice() {
  try {
    const res = await fetch(COINGECKO_URL);
    if (!res.ok) throw new Error(`CoinGecko responded with ${res.status}`);
    const data = await res.json();
    latestPrice = data.bitcoin.usd;
    lastUpdated = Date.now();
    return { price: latestPrice, lastUpdated };
  } catch (err) {
    console.error('Price fetch failed:', err.message);
    return null;
  }
}

export function startPricePoller(io) {
  // Fetch immediately on startup
  fetchPrice().then((data) => {
    if (data) {
      io.emit('priceUpdate', data);
    }
  });

  // Then poll every 30 seconds
  setInterval(async () => {
    const data = await fetchPrice();
    if (data) {
      io.emit('priceUpdate', data);
    }
  }, 30_000);
}
