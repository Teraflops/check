import React, { useState } from 'react';

function formatBytes(bytes) {
  if (bytes >= 1_000_000) return (bytes / 1_000_000).toFixed(2) + ' MB';
  if (bytes >= 1_000) return (bytes / 1_000).toFixed(1) + ' KB';
  return bytes + ' B';
}

function formatBTC(sats) {
  return (sats / 100_000_000).toFixed(8) + ' BTC';
}

function timeAgo(timestamp) {
  const seconds = Math.floor(Date.now() / 1000 - timestamp);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function formatDifficulty(diff) {
  if (diff >= 1e12) return (diff / 1e12).toFixed(2) + 'T';
  if (diff >= 1e9) return (diff / 1e9).toFixed(2) + 'G';
  if (diff >= 1e6) return (diff / 1e6).toFixed(2) + 'M';
  return diff.toLocaleString();
}

export default function BlockList({ blocks }) {
  const [expandedBlock, setExpandedBlock] = useState(null);

  if (!blocks || blocks.length === 0) {
    return (
      <div className="block-list-empty">
        <p>Loading blockchain data...</p>
      </div>
    );
  }

  function toggleExpand(height) {
    setExpandedBlock(expandedBlock === height ? null : height);
  }

  return (
    <div className="block-list">
      <div className="block-list-header">
        <h2>Latest Bitcoin Blocks</h2>
        <span className="block-count">{blocks.length} blocks</span>
      </div>

      <div className="blocks-grid">
        {blocks.map((block) => (
          <div
            key={block.height}
            className={`block-card ${expandedBlock === block.height ? 'expanded' : ''}`}
            onClick={() => toggleExpand(block.height)}
          >
            <div className="block-card-main">
              <div className="block-height-col">
                <span className="block-icon">&#9638;</span>
                <div>
                  <span className="block-height">#{block.height.toLocaleString()}</span>
                  <span className="block-time">{timeAgo(block.timestamp)}</span>
                </div>
              </div>

              <div className="block-miner-col">
                <span className="block-field-label">Mined by</span>
                <span className="block-miner">{block.pool}</span>
              </div>

              <div className="block-stat-col">
                <span className="block-field-label">Transactions</span>
                <span className="block-stat">{block.tx_count.toLocaleString()}</span>
              </div>

              <div className="block-stat-col">
                <span className="block-field-label">Size</span>
                <span className="block-stat">{formatBytes(block.size)}</span>
              </div>

              <div className="block-stat-col">
                <span className="block-field-label">Reward</span>
                <span className="block-stat reward">{formatBTC(block.reward)}</span>
              </div>
            </div>

            {expandedBlock === block.height && (
              <div className="block-card-details">
                <div className="detail-grid">
                  <div className="detail-item">
                    <span className="detail-label">Block Hash</span>
                    <span className="detail-value hash">{block.hash}</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Merkle Root</span>
                    <span className="detail-value hash">{block.merkle_root || '—'}</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Timestamp</span>
                    <span className="detail-value">
                      {new Date(block.timestamp * 1000).toLocaleString()}
                    </span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Difficulty</span>
                    <span className="detail-value">{formatDifficulty(block.difficulty)}</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Nonce</span>
                    <span className="detail-value">{block.nonce?.toLocaleString() || '—'}</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Bits</span>
                    <span className="detail-value">{block.bits || '—'}</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Weight</span>
                    <span className="detail-value">{(block.weight / 1000).toFixed(1)} KWU</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Total Fees</span>
                    <span className="detail-value">{formatBTC(block.total_fees)}</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Median Fee Rate</span>
                    <span className="detail-value">{block.median_fee} sat/vB</span>
                  </div>
                  <div className="detail-item">
                    <span className="detail-label">Avg Fee Rate</span>
                    <span className="detail-value">{block.avg_fee_rate} sat/vB</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
