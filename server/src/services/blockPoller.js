const MEMPOOL_API = 'https://mempool.space/api';

let latestBlocks = [];
let lastKnownHeight = 0;

export function getLatestBlocks() {
  return latestBlocks;
}

async function fetchBlocks() {
  try {
    const res = await fetch(`${MEMPOOL_API}/v1/blocks`);
    if (!res.ok) throw new Error(`Mempool API responded with ${res.status}`);
    const blocks = await res.json();

    latestBlocks = blocks.map((block) => ({
      height: block.height,
      hash: block.id,
      timestamp: block.timestamp,
      size: block.size,
      weight: block.weight,
      tx_count: block.tx_count,
      difficulty: block.difficulty,
      nonce: block.nonce,
      bits: block.bits,
      merkle_root: block.merkle_root,
      pool: block.extras?.pool?.name || 'Unknown',
      pool_slug: block.extras?.pool?.slug || null,
      reward: block.extras?.reward || 0,
      total_fees: block.extras?.totalFees || 0,
      median_fee: block.extras?.medianFee || 0,
      avg_fee_rate: block.extras?.avgFeeRate || 0,
    }));

    const newHeight = latestBlocks.length > 0 ? latestBlocks[0].height : 0;
    const hasNewBlock = newHeight > lastKnownHeight;
    lastKnownHeight = newHeight;

    return { blocks: latestBlocks, hasNewBlock };
  } catch (err) {
    console.error('Block fetch failed:', err.message);
    return null;
  }
}

export function startBlockPoller(io) {
  // Fetch immediately on startup
  fetchBlocks().then((data) => {
    if (data) {
      io.emit('blocksUpdate', data.blocks);
    }
  });

  // Poll every 30 seconds for new blocks (~10 min block time, so this is fine)
  setInterval(async () => {
    const data = await fetchBlocks();
    if (data) {
      io.emit('blocksUpdate', data.blocks);
      if (data.hasNewBlock) {
        io.emit('newBlock', data.blocks[0]);
      }
    }
  }, 30_000);
}
