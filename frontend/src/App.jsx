import { useEffect, useState } from "react";
import { api } from "./api.js";
import DecisionView from "./components/DecisionView.jsx";
import AccuracyView from "./components/AccuracyView.jsx";

export default function App() {
  const [tab, setTab] = useState("decision");
  const [cutoff, setCutoff] = useState("09:00");
  const [meta, setMeta] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setError(null);
    api.meta(cutoff).then(setMeta).catch((e) => setError(e.message));
  }, [cutoff]);

  return (
    <div className="app">
      <header>
        <div>
          <h1>Wind Forecast Desk</h1>
          <p className="sub">GB day-ahead buying, January 2026 decisions. National wind only (Elexon).</p>
        </div>
        <label className="cutoff">
          Decision time on the day before delivery (London)
          <input type="time" value={cutoff} onChange={(e) => e.target.value && setCutoff(e.target.value)} />
        </label>
      </header>

      <nav>
        <button className={tab === "decision" ? "on" : ""} onClick={() => setTab("decision")}>
          Forecast at decision time
        </button>
        <button className={tab === "accuracy" ? "on" : ""} onClick={() => setTab("accuracy")}>
          How accurate is it?
        </button>
      </nav>

      {error && <div className="alert">Could not load data: {error}</div>}
      {meta && tab === "decision" && <DecisionView meta={meta} cutoff={cutoff} />}
      {meta && tab === "accuracy" && <AccuracyView cutoff={cutoff} />}

      <footer>
        Error = forecast minus actual. Positive means the forecast was too high, so you would have bought too little
        from other sources. 
      </footer>
    </div>
  );
}
