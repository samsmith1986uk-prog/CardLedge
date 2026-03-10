import { useState, useEffect, useRef } from "react";

// ─── Mock data for demo (replace API_BASE with your backend URL) ──────────────
const API_BASE = "http://localhost:8000"; // Your FastAPI backend

const MOCK_CARD = {
  cert_number: "85028490",
  grading_company: "PSA",
  card_details: {
    cert_number: "85028490",
    grading_company: "PSA",
    grade: "10",
    full_grade: "GEM-MT 10",
    subject: "LeBron James",
    year: "2003",
    brand: "Topps Chrome",
    series: "Refractor",
    variety: "Rookie Card RC",
    card_number: "111",
    image_url: "https://d1htnxwo4o0jhw.cloudfront.net/cert/85/02/84/90/cert85028490_front.jpg",
    pop: 312,
    pop_higher: 0,
    source: "PSA Public API",
  },
  sales_data: [
    { source: "eBay", title: "2003 Topps Chrome LeBron James Refractor RC PSA 10 #111", price: 4800, date: "2025-02-18", url: "#" },
    { source: "Goldin", title: "2003 Topps Chrome LeBron James Refractor Rookie PSA 10", price: 5200, date: "2025-01-30", url: "#" },
    { source: "130point (eBay)", title: "2003 Topps Chrome LeBron Refractor RC #111 PSA 10", price: 4600, date: "2025-01-15", url: "#" },
    { source: "Heritage", title: "2003-04 Topps Chrome LeBron James RC Refractor PSA GEM 10", price: 5500, date: "2024-12-10", url: "#" },
    { source: "eBay", title: "2003 Topps Chrome LeBron James RC Refractor PSA 10 Gem Mint", price: 4400, date: "2024-11-28", url: "#" },
    { source: "Goldin", title: "2003 Topps Chrome LeBron James Refractor Rookie Card PSA 10", price: 5800, date: "2024-10-15", url: "#" },
    { source: "eBay", title: "2003 Topps Chrome LeBron James Refractor PSA 10 RC", price: 4200, date: "2024-09-22", url: "#" },
    { source: "130point (Fanatics)", title: "2003 Topps Chrome LeBron #111 Refractor PSA 10", price: 4750, date: "2024-08-14", url: "#" },
  ],
  market_summary: {
    avg_price: 4906,
    median_price: 4800,
    low_price: 4200,
    high_price: 5800,
    total_sales_found: 8,
    sources_checked: 4,
  },
};

const SOURCE_COLORS = {
  eBay: "#e53238",
  Goldin: "#c9a84c",
  Heritage: "#8b0000",
  "130point (eBay)": "#2c3e50",
  "130point (Fanatics)": "#2c3e50",
  "130point (Goldin)": "#2c3e50",
  "Fanatics": "#cc0000",
  BGS: "#1565c0",
  PSA: "#003087",
};

const SCRAPE_STAGES = [
  { label: "Fetching cert from PSA...", icon: "🔍" },
  { label: "Searching eBay sold listings...", icon: "🛒" },
  { label: "Querying 130point comps...", icon: "📊" },
  { label: "Checking Goldin auctions...", icon: "🏆" },
  { label: "Scanning Heritage archives...", icon: "📜" },
  { label: "Computing market model...", icon: "⚡" },
];

function LoadingTerminal({ stage, stageIndex }) {
  const [dots, setDots] = useState("");
  const [lines, setLines] = useState([]);
  const termRef = useRef(null);

  useEffect(() => {
    const interval = setInterval(() => setDots(d => d.length >= 3 ? "" : d + "."), 400);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    setLines(prev => [...prev.slice(-12), `${SCRAPE_STAGES[stageIndex]?.icon || "▶"} ${stage}`]);
    if (termRef.current) termRef.current.scrollTop = termRef.current.scrollHeight;
  }, [stage, stageIndex]);

  return (
    <div style={{
      background: "#050508",
      border: "1px solid #1e3a1e",
      borderRadius: "12px",
      overflow: "hidden",
      width: "100%",
      maxWidth: "560px",
    }}>
      <div style={{
        background: "#0a1a0a",
        padding: "10px 16px",
        display: "flex", alignItems: "center", gap: "8px",
        borderBottom: "1px solid #1e3a1e",
      }}>
        <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#ff5f57" }} />
        <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#febc2e" }} />
        <div style={{ width: 10, height: 10, borderRadius: "50%", background: "#28c840" }} />
        <span style={{ marginLeft: 8, fontSize: 11, color: "#3a6b3a", fontFamily: "monospace" }}>cardledge — scraper</span>
      </div>
      <div ref={termRef} style={{
        padding: "16px",
        height: "200px",
        overflowY: "auto",
        fontFamily: "'Courier New', monospace",
        fontSize: "12px",
        lineHeight: "1.8",
      }}>
        {lines.map((line, i) => (
          <div key={i} style={{ color: i === lines.length - 1 ? "#00ff88" : "#3a6b3a" }}>
            {i === lines.length - 1 ? `→ ${line}${dots}` : `✓ ${line}`}
          </div>
        ))}
      </div>
      <div style={{ padding: "10px 16px", borderTop: "1px solid #1e3a1e" }}>
        <div style={{ height: 3, background: "#0a2a0a", borderRadius: 2 }}>
          <div style={{
            height: "100%",
            width: `${((stageIndex + 1) / SCRAPE_STAGES.length) * 100}%`,
            background: "linear-gradient(90deg, #00ff88, #00cc66)",
            borderRadius: 2,
            transition: "width 0.5s ease",
            boxShadow: "0 0 8px #00ff8880",
          }} />
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
          <span style={{ fontSize: 9, color: "#3a6b3a", fontFamily: "monospace" }}>
            {stageIndex + 1}/{SCRAPE_STAGES.length} sources
          </span>
          <span style={{ fontSize: 9, color: "#3a6b3a", fontFamily: "monospace" }}>
            {Math.round(((stageIndex + 1) / SCRAPE_STAGES.length) * 100)}% complete
          </span>
        </div>
      </div>
    </div>
  );
}

function PriceChart({ sales }) {
  if (!sales || sales.length < 2) return null;
  const prices = sales.map(s => s.price).filter(Boolean);
  const max = Math.max(...prices);
  const min = Math.min(...prices);
  const range = max - min || 1;
  const w = 100, h = 48;

  const points = sales
    .filter(s => s.price)
    .slice()
    .reverse()
    .map((s, i, arr) => {
      const x = (i / (arr.length - 1)) * w;
      const y = h - ((s.price - min) / range) * (h - 4) - 2;
      return { x, y, ...s };
    });

  const pathD = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
  const areaD = `${pathD} L ${w} ${h} L 0 ${h} Z`;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: "64px", overflow: "visible" }}>
      <defs>
        <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#00ff88" stopOpacity="0.3" />
          <stop offset="100%" stopColor="#00ff88" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaD} fill="url(#chartGrad)" />
      <path d={pathD} fill="none" stroke="#00ff88" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      {points.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r="2" fill="#00ff88" />
      ))}
    </svg>
  );
}

function InvestmentVerdict({ summary, cardDetails }) {
  if (!summary) return null;

  // Compute score
  const popScore = cardDetails?.pop ? Math.max(0, 100 - cardDetails.pop / 10) : 50;
  const priceSpread = (summary.high_price - summary.low_price) / summary.avg_price;
  const spreadScore = Math.max(0, 100 - priceSpread * 80);
  const volumeScore = Math.min(100, summary.total_sales_found * 5);
  const score = Math.round((popScore * 0.3 + spreadScore * 0.3 + volumeScore * 0.4));

  let verdict, verdictColor, verdictDesc;
  if (score >= 72) { verdict = "STRONG BUY"; verdictColor = "#00ff88"; verdictDesc = "High liquidity, tight spread, strong demand"; }
  else if (score >= 58) { verdict = "BUY"; verdictColor = "#7bff6e"; verdictDesc = "Good market activity, reasonable entry point"; }
  else if (score >= 44) { verdict = "HOLD"; verdictColor = "#ffd700"; verdictDesc = "Stable market, monitor for better entry"; }
  else if (score >= 30) { verdict = "WEAK"; verdictColor = "#ff9f43"; verdictDesc = "Low volume, high spread — proceed carefully"; }
  else { verdict = "AVOID"; verdictColor = "#ff4757"; verdictDesc = "Insufficient data or unfavorable conditions"; }

  const r = 30, cx = 40, cy = 40;
  const circ = Math.PI * r;
  const offset = circ - (score / 100) * circ;

  return (
    <div style={{
      background: "#0a0a14",
      border: `1px solid ${verdictColor}33`,
      borderRadius: 12,
      padding: "20px",
      display: "flex",
      alignItems: "center",
      gap: 20,
    }}>
      <svg width="80" height="52" viewBox="0 0 80 52">
        <path d={`M 10,40 A ${r},${r} 0 0,1 70,40`} fill="none" stroke="#1a1a2e" strokeWidth="7" strokeLinecap="round" />
        <path d={`M 10,40 A ${r},${r} 0 0,1 70,40`} fill="none" stroke={verdictColor}
          strokeWidth="7" strokeLinecap="round"
          strokeDasharray={circ} strokeDashoffset={offset}
          style={{ transition: "stroke-dashoffset 1s ease" }} />
        <text x="40" y="38" textAnchor="middle" fill={verdictColor} fontSize="14" fontWeight="700" fontFamily="monospace">{score}</text>
        <text x="40" y="50" textAnchor="middle" fill="#555" fontSize="7" fontFamily="monospace">SCORE</text>
      </svg>
      <div>
        <div style={{ fontSize: 18, fontWeight: 900, color: verdictColor, letterSpacing: 3, fontFamily: "monospace" }}>{verdict}</div>
        <div style={{ fontSize: 11, color: "#888", marginTop: 4 }}>{verdictDesc}</div>
        <div style={{ fontSize: 10, color: "#555", marginTop: 6, fontFamily: "monospace" }}>
          Pop: {cardDetails?.pop ?? "N/A"} · Sources: {summary.sources_checked} · Sales: {summary.total_sales_found}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [certInput, setCertInput] = useState("");
  const [gradingCo, setGradingCo] = useState("PSA");
  const [loading, setLoading] = useState(false);
  const [stageIndex, setStageIndex] = useState(0);
  const [stageLabel, setStageLabel] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState("overview");
  const [demoMode, setDemoMode] = useState(false);

  async function handleLookup() {
    if (!certInput.trim()) return;
    setLoading(true);
    setResult(null);
    setError("");
    setStageIndex(0);

    // Animate through stages
    const stageInterval = setInterval(() => {
      setStageIndex(prev => {
        const next = prev + 1;
        if (next < SCRAPE_STAGES.length) {
          setStageLabel(SCRAPE_STAGES[next].label);
          return next;
        }
        clearInterval(stageInterval);
        return prev;
      });
    }, 600);

    setStageLabel(SCRAPE_STAGES[0].label);

    try {
      if (demoMode) {
        await new Promise(r => setTimeout(r, SCRAPE_STAGES.length * 620));
        clearInterval(stageInterval);
        setResult(MOCK_CARD);
      } else {
        const resp = await fetch(`${API_BASE}/lookup/${gradingCo}/${certInput.trim()}`);
        clearInterval(stageInterval);
        if (!resp.ok) throw new Error(`Server error: ${resp.status}`);
        const data = await resp.json();
        setResult(data);
      }
    } catch (e) {
      clearInterval(stageInterval);
      if (e.message.includes("fetch") || e.message.includes("Failed")) {
        setError("Backend not running. Enable Demo Mode to preview with sample data.");
      } else {
        setError(e.message);
      }
    } finally {
      setLoading(false);
    }
  }

  const card = result?.card_details;
  const sales = result?.sales_data || [];
  const summary = result?.market_summary;

  return (
    <div style={{
      minHeight: "100vh",
      background: "#07070e",
      color: "#e0e0e0",
      fontFamily: "'Courier New', monospace",
    }}>
      {/* Header */}
      <div style={{
        borderBottom: "1px solid #12122a",
        padding: "14px 28px",
        display: "flex",
        alignItems: "center",
        gap: 14,
        background: "#09091a",
      }}>
        <div style={{
          width: 36, height: 36, borderRadius: 8,
          background: "linear-gradient(135deg, #00ff88 0%, #00aaff 100%)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 18, fontWeight: 900, color: "#000",
        }}>C</div>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: 4, color: "#fff" }}>CARDLEDGE</div>
          <div style={{ fontSize: 8, color: "#444", letterSpacing: 3 }}>CERT LOOKUP · MARKET INTELLIGENCE</div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 10, alignItems: "center" }}>
          <label style={{ display: "flex", gap: 7, alignItems: "center", cursor: "pointer", fontSize: 10, color: demoMode ? "#00ff88" : "#555" }}>
            <div onClick={() => setDemoMode(p => !p)} style={{
              width: 32, height: 16,
              background: demoMode ? "#00ff8830" : "#12122a",
              border: `1px solid ${demoMode ? "#00ff88" : "#333"}`,
              borderRadius: 8, cursor: "pointer", position: "relative",
            }}>
              <div style={{
                width: 10, height: 10, borderRadius: "50%",
                background: demoMode ? "#00ff88" : "#444",
                position: "absolute", top: 2,
                left: demoMode ? 18 : 2,
                transition: "left 0.2s",
              }} />
            </div>
            DEMO MODE
          </label>
        </div>
      </div>

      {/* Main content */}
      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "32px 24px" }}>

        {/* Search area */}
        <div style={{ textAlign: "center", marginBottom: 40 }}>
          <div style={{ fontSize: 28, fontWeight: 900, color: "#fff", letterSpacing: 2, marginBottom: 6 }}>
            CERT LOOKUP
          </div>
          <div style={{ fontSize: 12, color: "#555", marginBottom: 28, letterSpacing: 2 }}>
            Enter a PSA or Beckett cert number to pull live market data from 5+ sources
          </div>

          {/* Search bar */}
          <div style={{
            display: "inline-flex",
            gap: 0,
            background: "#0d0d1e",
            border: "1px solid #2a2a4e",
            borderRadius: 12,
            overflow: "hidden",
            boxShadow: "0 0 40px #00ff8810",
            width: "100%",
            maxWidth: 580,
          }}>
            {/* Grading company toggle */}
            <div style={{ display: "flex", borderRight: "1px solid #2a2a4e" }}>
              {["PSA", "BGS", "SGC"].map(g => (
                <div key={g} onClick={() => setGradingCo(g)} style={{
                  padding: "14px 14px",
                  cursor: "pointer",
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: 1,
                  color: gradingCo === g ? "#00ff88" : "#444",
                  background: gradingCo === g ? "#00ff8812" : "transparent",
                  transition: "all 0.15s",
                  borderRight: g !== "SGC" ? "1px solid #1a1a3a" : "none",
                }}>{g}</div>
              ))}
            </div>

            <input
              value={certInput}
              onChange={e => setCertInput(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleLookup()}
              placeholder={demoMode ? "Try: 85028490  (demo)" : `Enter ${gradingCo} cert number...`}
              style={{
                flex: 1,
                background: "transparent",
                border: "none",
                padding: "14px 18px",
                color: "#fff",
                fontSize: 14,
                fontFamily: "monospace",
                outline: "none",
                letterSpacing: 1,
              }}
            />

            <button onClick={handleLookup} disabled={loading} style={{
              padding: "14px 24px",
              background: loading ? "#1a1a3a" : "linear-gradient(135deg, #00ff8820, #00aaff20)",
              border: "none",
              borderLeft: "1px solid #2a2a4e",
              color: loading ? "#444" : "#00ff88",
              fontSize: 11,
              fontFamily: "monospace",
              letterSpacing: 2,
              cursor: loading ? "not-allowed" : "pointer",
            }}>
              {loading ? "..." : "SEARCH ▶"}
            </button>
          </div>

          {error && (
            <div style={{
              marginTop: 16, padding: "10px 16px",
              background: "#ff475710", border: "1px solid #ff475733",
              borderRadius: 8, color: "#ff4757", fontSize: 12, display: "inline-block",
            }}>{error}</div>
          )}
        </div>

        {/* Loading terminal */}
        {loading && (
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 32 }}>
            <LoadingTerminal stage={stageLabel} stageIndex={stageIndex} />
          </div>
        )}

        {/* Results */}
        {result && !loading && (
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

            {/* Card hero */}
            <div style={{
              display: "flex",
              gap: 24,
              background: "#0a0a1a",
              border: "1px solid #1a1a3a",
              borderRadius: 16,
              padding: 24,
            }}>
              {/* Card image */}
              <div style={{
                flexShrink: 0,
                width: 130,
                minHeight: 180,
                background: "linear-gradient(145deg, #12122a, #0d0d1e)",
                border: "1px solid #2a2a4e",
                borderRadius: 10,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                overflow: "hidden",
                position: "relative",
              }}>
                {card?.image_url ? (
                  <img
                    src={card.image_url}
                    alt={card.subject}
                    style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: 10 }}
                    onError={e => { e.target.style.display = "none"; }}
                  />
                ) : (
                  <div style={{ fontSize: 36, opacity: 0.2 }}>🃏</div>
                )}
              </div>

              {/* Card info */}
              <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 10 }}>
                <div>
                  <div style={{ fontSize: 22, fontWeight: 900, color: "#fff", letterSpacing: 1 }}>
                    {card?.subject || "Unknown Player"}
                  </div>
                  <div style={{ fontSize: 12, color: "#666", marginTop: 3 }}>
                    {card?.year} {card?.brand} {card?.series} {card?.variety && `· ${card.variety}`}
                  </div>
                  <div style={{ fontSize: 11, color: "#444", marginTop: 2 }}>
                    #{card?.card_number} · Cert: {result.cert_number}
                  </div>
                </div>

                {/* Grade badge */}
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
                  <div style={{
                    padding: "6px 16px",
                    background: gradingCo === "PSA" ? "#00308720" : "#1565c020",
                    border: `2px solid ${gradingCo === "PSA" ? "#003087" : "#1565c0"}`,
                    borderRadius: 8,
                    fontSize: 18,
                    fontWeight: 900,
                    color: gradingCo === "PSA" ? "#4da6ff" : "#64b5f6",
                    letterSpacing: 2,
                  }}>
                    {result.grading_company} {card?.grade || "?"}
                  </div>

                  {card?.is_black_label && (
                    <div style={{
                      padding: "4px 12px",
                      background: "#1a1a2a",
                      border: "1px solid #ffd700",
                      borderRadius: 6, fontSize: 10, color: "#ffd700", letterSpacing: 2,
                    }}>⭐ BLACK LABEL</div>
                  )}

                  {card?.pop !== undefined && (
                    <div style={{ fontSize: 11, color: "#666", fontFamily: "monospace" }}>
                      Pop {result.grading_company} {card.grade}: <span style={{ color: "#aaa" }}>{card.pop}</span>
                      {card.pop_higher === 0 && card.grade === "10" &&
                        <span style={{ color: "#00ff88", marginLeft: 6 }}>· HIGHEST GRADE</span>}
                    </div>
                  )}
                </div>

                {/* BGS subgrades */}
                {card?.subgrades && Object.values(card.subgrades).some(Boolean) && (
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {Object.entries(card.subgrades).map(([key, val]) => val && (
                      <div key={key} style={{
                        padding: "3px 10px",
                        background: "#12122a", border: "1px solid #2a2a4e", borderRadius: 5,
                        fontSize: 10, color: "#888",
                      }}>
                        <span style={{ color: "#555" }}>{key}: </span>
                        <span style={{ color: parseFloat(val) === 10 ? "#00ff88" : "#aaa" }}>{val}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Prices row */}
                {summary && (
                  <div style={{ display: "flex", gap: 20, flexWrap: "wrap", marginTop: 4 }}>
                    {[
                      ["AVG", summary.avg_price, "#fff"],
                      ["LOW", summary.low_price, "#00ff88"],
                      ["HIGH", summary.high_price, "#ff9f43"],
                      ["MEDIAN", summary.median_price, "#00aaff"],
                    ].map(([label, val, color]) => (
                      <div key={label}>
                        <div style={{ fontSize: 8, color: "#555", letterSpacing: 1 }}>{label}</div>
                        <div style={{ fontSize: 18, fontWeight: 700, color }}>${val?.toLocaleString()}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Verdict panel */}
              <div style={{ flexShrink: 0, width: 200 }}>
                <InvestmentVerdict summary={summary} cardDetails={card} />
              </div>
            </div>

            {/* Tabs */}
            <div>
              <div style={{ display: "flex", borderBottom: "1px solid #1a1a3a", marginBottom: 16 }}>
                {["overview", "sales", "sources"].map(tab => (
                  <div key={tab} onClick={() => setActiveTab(tab)} style={{
                    padding: "9px 20px",
                    fontSize: 10, letterSpacing: 2,
                    color: activeTab === tab ? "#00ff88" : "#444",
                    borderBottom: activeTab === tab ? "2px solid #00ff88" : "2px solid transparent",
                    cursor: "pointer",
                    textTransform: "uppercase",
                    marginBottom: -1,
                  }}>{tab}</div>
                ))}
              </div>

              {activeTab === "overview" && summary && (
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                  {/* Price history chart */}
                  <div style={{ background: "#0a0a1a", border: "1px solid #1a1a3a", borderRadius: 12, padding: 16, gridColumn: "1 / -1" }}>
                    <div style={{ fontSize: 9, color: "#555", letterSpacing: 2, marginBottom: 10 }}>PRICE HISTORY (RECENT SALES)</div>
                    <PriceChart sales={sales} />
                    <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
                      <span style={{ fontSize: 9, color: "#444" }}>{sales[sales.length - 1]?.date}</span>
                      <span style={{ fontSize: 9, color: "#444" }}>{sales[0]?.date}</span>
                    </div>
                  </div>

                  {/* Stats */}
                  {[
                    { label: "Total Sales Found", value: summary.total_sales_found, unit: "sales" },
                    { label: "Sources Scraped", value: summary.sources_checked, unit: "platforms" },
                    { label: "Price Range", value: `$${summary.low_price.toLocaleString()} – $${summary.high_price.toLocaleString()}`, unit: "" },
                    { label: "Population (this grade)", value: card?.pop ?? "N/A", unit: "copies" },
                  ].map(({ label, value, unit }) => (
                    <div key={label} style={{ background: "#0a0a1a", border: "1px solid #1a1a3a", borderRadius: 10, padding: "14px 16px" }}>
                      <div style={{ fontSize: 9, color: "#555", letterSpacing: 1, marginBottom: 4 }}>{label.toUpperCase()}</div>
                      <div style={{ fontSize: 18, color: "#fff", fontWeight: 700 }}>{value} <span style={{ fontSize: 11, color: "#555", fontWeight: 400 }}>{unit}</span></div>
                    </div>
                  ))}
                </div>
              )}

              {activeTab === "sales" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {sales.length === 0 ? (
                    <div style={{ color: "#444", fontSize: 13, padding: 20, textAlign: "center" }}>No sales data found</div>
                  ) : sales.map((sale, i) => {
                    const sourceColor = SOURCE_COLORS[sale.source] || "#666";
                    return (
                      <a key={i} href={sale.url || "#"} target="_blank" rel="noreferrer" style={{ textDecoration: "none" }}>
                        <div style={{
                          display: "flex", alignItems: "center", gap: 12,
                          background: "#0a0a1a", border: "1px solid #1a1a3a", borderRadius: 9,
                          padding: "11px 14px",
                          transition: "border-color 0.15s",
                        }}>
                          <div style={{
                            flexShrink: 0, padding: "3px 8px",
                            background: sourceColor + "18",
                            border: `1px solid ${sourceColor}44`,
                            borderRadius: 5, fontSize: 9, color: sourceColor, minWidth: 64, textAlign: "center",
                          }}>{sale.source}</div>
                          <div style={{ flex: 1, fontSize: 11, color: "#999", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {sale.title}
                          </div>
                          <div style={{ flexShrink: 0, fontSize: 9, color: "#555", fontFamily: "monospace" }}>{sale.date}</div>
                          <div style={{ flexShrink: 0, fontSize: 14, fontWeight: 700, color: "#fff", minWidth: 80, textAlign: "right", fontFamily: "monospace" }}>
                            ${sale.price?.toLocaleString()}
                          </div>
                        </div>
                      </a>
                    );
                  })}
                </div>
              )}

              {activeTab === "sources" && (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10 }}>
                  {Object.entries(
                    sales.reduce((acc, s) => {
                      const src = s.source?.split("(")[0].trim() || "Unknown";
                      if (!acc[src]) acc[src] = { count: 0, prices: [] };
                      acc[src].count++;
                      if (s.price) acc[src].prices.push(s.price);
                      return acc;
                    }, {})
                  ).map(([src, data]) => {
                    const avg = data.prices.length ? Math.round(data.prices.reduce((a, b) => a + b, 0) / data.prices.length) : 0;
                    const color = SOURCE_COLORS[src] || "#888";
                    return (
                      <div key={src} style={{ background: "#0a0a1a", border: `1px solid ${color}33`, borderRadius: 10, padding: "14px 16px" }}>
                        <div style={{ fontSize: 11, fontWeight: 700, color, marginBottom: 6 }}>{src}</div>
                        <div style={{ fontSize: 11, color: "#888" }}>{data.count} sale{data.count !== 1 ? "s" : ""}</div>
                        {avg > 0 && <div style={{ fontSize: 14, color: "#fff", fontWeight: 700, marginTop: 4 }}>${avg.toLocaleString()} avg</div>}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {result.errors?.length > 0 && (
              <div style={{ background: "#0a0a1a", border: "1px solid #ff475722", borderRadius: 10, padding: "12px 16px" }}>
                <div style={{ fontSize: 9, color: "#ff4757", letterSpacing: 2, marginBottom: 6 }}>SCRAPER WARNINGS</div>
                {result.errors.map((e, i) => (
                  <div key={i} style={{ fontSize: 10, color: "#666", fontFamily: "monospace", marginBottom: 3 }}>⚠ {e}</div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Empty state */}
        {!result && !loading && (
          <div style={{ textAlign: "center", padding: "60px 0", color: "#333" }}>
            <div style={{ fontSize: 48, marginBottom: 16, opacity: 0.5 }}>🃏</div>
            <div style={{ fontSize: 13, letterSpacing: 3, marginBottom: 8 }}>ENTER A CERT NUMBER ABOVE</div>
            <div style={{ fontSize: 11, color: "#2a2a3a" }}>PSA, BGS, and SGC cert numbers supported</div>
            <div style={{ marginTop: 24, fontSize: 11, color: "#2a2a3a" }}>
              Scrapes: eBay · 130point · Goldin · Heritage · Fanatics · PSA Pop
            </div>
            {demoMode && (
              <div style={{
                marginTop: 24, display: "inline-block",
                padding: "8px 18px", background: "#00ff8810",
                border: "1px solid #00ff8833", borderRadius: 8,
                fontSize: 11, color: "#00ff88",
              }}>
                Demo mode ON — try cert: 85028490
              </div>
            )}
          </div>
        )}
      </div>

      <style>{`
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: #07070e; }
        ::-webkit-scrollbar-thumb { background: #2a2a4e; border-radius: 2px; }
        input::placeholder { color: #2a2a4a; }
      `}</style>
    </div>
  );
}
