import { useEffect, useState } from "react";
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, Legend, CartesianGrid, ResponsiveContainer, ReferenceLine } from "recharts";
import { api, fmtMW, fmtNum } from "../api.js";

export default function AccuracyView({ cutoff }) {
  const [summary, setSummary] = useState(null);
  const [daily, setDaily] = useState([]);
  const [byHour, setByHour] = useState([]);
  const [byHorizon, setByHorizon] = useState([]);
  const [level, setLevel] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setError(null);
    Promise.all([api.summary(cutoff), api.daily(cutoff), api.byHour(cutoff), api.byHorizon(), api.byLevel(cutoff)])
      .then(([s, d, h, hz, lv]) => {
        setLevel(lv);
        setSummary(s);
        setDaily(d);
        setByHour(h);
        setByHorizon(hz);
      })
      .catch((e) => setError(e.message));
  }, [cutoff]);

  if (error) return <div className="alert">{error}</div>;
  if (!summary) return <p className="muted">Loading…</p>;
  const o = summary.overall;

  return (
    <section>
      <p className="lead">
        These numbers compare the forecast you would really have had at <b>{cutoff}</b> the day before with what the wind
        farms produced, over {fmtNum(o.n)} forecast points.
      </p>

      <div className="cards">
        <Card label="Average miss (MAE)" value={fmtMW(o.mae)} hint="Typical size of the error" />
        <Card label="Average miss as % of output" value={o.nmae_pct != null ? `${fmtNum(o.nmae_pct, 1)}%` : "n/a"} hint="MAE ÷ average actual wind" />
        <Card label="Large-miss measure (RMSE)" value={fmtMW(o.rmse)} hint="Punishes big misses more" />
        <Card label="Bias" value={fmtMW(o.bias)} hint="Positive = forecast too high on average" />
        <Card label="90% of misses between" value={`${fmtNum(o.p05_error)} and ${fmtNum(o.p95_error)} MW`} hint="5th to 95th percentile of error" />
        <Card label="Worst over / under" value={`${fmtNum(o.max_over)} / ${fmtNum(o.max_under)} MW`} hint="Single worst forecast points" />
      </div>

      <WalkForward wf={summary.walk_forward} />

      <div className="grid">
        <div className="panel">
          <h2>Average miss by delivery day</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={daily.map((d) => ({ day: d.delivery_day.slice(5), MAE: d.mae, Bias: d.bias }))}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="day" interval={2} />
              <YAxis />
              <Tooltip formatter={(v) => fmtMW(v)} />
              <Legend />
              <Bar dataKey="MAE" fill="#0b7285" isAnimationActive={false} />
              <Bar dataKey="Bias" fill="#e8590c" isAnimationActive={false} />
              <ReferenceLine y={0} stroke="#555" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="panel">
          <h2>Error against how far ahead the forecast was made</h2>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={byHorizon.map((h) => ({ x: `${h.horizon_from_h}-${h.horizon_to_h}h`, MAE: h.mae, RMSE: h.rmse }))}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="x" interval={Math.ceil(byHorizon.length / 10)} />
              <YAxis />
              <Tooltip formatter={(v) => fmtMW(v)} />
              <Legend />
              <Line dataKey="MAE" stroke="#0b7285" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line dataKey="RMSE" stroke="#7048e8" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
          <p className="muted">Uses every forecast published in January, not only the decision-time ones.</p>
        </div>

        <div className="panel">
          <h2>Average miss by hour of day</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={byHour.map((h) => ({ hour: `${String(h.hour).padStart(2, "0")}:00`, MAE: h.mae, Bias: h.bias }))}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="hour" interval={2} />
              <YAxis />
              <Tooltip formatter={(v) => fmtMW(v)} />
              <Legend />
              <Bar dataKey="MAE" fill="#0b7285" isAnimationActive={false} />
              <Bar dataKey="Bias" fill="#e8590c" isAnimationActive={false} />
              <ReferenceLine y={0} stroke="#555" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="panel">
          <h2>How errors are spread</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={summary.histogram.map((b) => ({ x: `${b.from_mw}`, Count: b.count }))} margin={{ top: 5, right: 20, left: 0, bottom: 28 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="x" interval={Math.ceil(summary.histogram.length / 8)} label={{ value: "Error in MW (bucket start)", position: "insideBottom", offset: -18 }} />
              <YAxis />
              <Tooltip />
              <Bar dataKey="Count" fill="#0b7285" isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <LevelPanel level={level} />

      <div className="panel">
        <h2>Daily detail</h2>
        <div className="tablewrap">
          <table>
            <thead>
              <tr><th>Delivery day</th><th>MAE (MW)</th><th>RMSE (MW)</th><th>Bias (MW)</th><th>Forecast MWh</th><th>Actual MWh</th></tr>
            </thead>
            <tbody>
              {daily.map((d) => (
                <tr key={d.delivery_day}>
                  <td>{d.delivery_day}</td>
                  <td>{fmtNum(d.mae)}</td><td>{fmtNum(d.rmse)}</td><td>{fmtNum(d.bias)}</td>
                  <td>{fmtNum(d.forecast_mwh)}</td><td>{fmtNum(d.actual_mwh)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function Card({ label, value, hint }) {
  return (
    <div className="card">
      <div className="card-label">{label}</div>
      <div className="card-value">{value}</div>
      {hint && <div className="card-hint">{hint}</div>}
    </div>
  );
}

function WalkForward({ wf }) {
  if (!wf || !wf.days_evaluated) {
    return null;
  }
  const r = wf.raw, c = wf.corrected;
  const gain = r.mae ? ((r.mae - c.mae) / r.mae) * 100 : null;
  return (
    <div className="panel">
      <h2>Would removing the usual bias have helped?</h2>
      <p className="muted">
        Backtest over {wf.days_evaluated} days. Each day was corrected using only the days whose results were already known
        at the decision time, so nothing from the future was used.
      </p>
      <div className="cards">
        <Card label="Average miss (MAE), raw" value={fmtMW(r.mae)} />
        <Card label="Average miss (MAE), corrected" value={fmtMW(c.mae)} hint={gain != null ? `${fmtNum(gain, 0)}% smaller` : ""} />
        <Card label="RMSE, raw → corrected" value={`${fmtNum(r.rmse)} → ${fmtNum(c.rmse)}`} hint="MW" />
        <Card label="Bias, raw → corrected" value={`${fmtNum(r.bias)} → ${fmtNum(c.bias)}`} hint="MW" />
      </div>
    </div>
  );
}

function LevelPanel({ level }) {
  if (!level || !level.bins || level.bins.length === 0) return null;
  const growing = level.slope != null && level.slope > 0.02 && level.r != null && level.r > 0.2;
  return (
    <div className="panel">
      <h2>Is the miss bigger when more wind is forecast?</h2>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={level.bins.map((b) => ({ x: `${fmtNum(b.from_mw / 1000, 1)}-${fmtNum(b.to_mw / 1000, 1)} GW`, Bias: b.bias, MAE: b.mae, n: b.n }))}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="x" />
          <YAxis />
          <Tooltip formatter={(v, name, p) => [fmtMW(v), name]} labelFormatter={(l, p) => `${l} forecast (${p?.[0]?.payload?.n} points)`} />
          <Legend />
          <Bar dataKey="Bias" fill="#e8590c" isAnimationActive={false} />
          <Bar dataKey="MAE" fill="#0b7285" isAnimationActive={false} />
          <ReferenceLine y={0} stroke="#555" />
        </BarChart>
      </ResponsiveContainer>
      <p className="muted">
        For every extra 1,000 MW forecast, the forecast is too high by about {fmtNum(level.slope * 1000)} MW more
        (correlation {fmtNum(level.r, 2)}).{" "}
        {growing
          ? "The miss grows with the wind level. Possible reasons are curtailment on very windy days or the two datasets not covering the same wind farms. This data cannot tell which."
          : "There is no strong link between the forecast level and the miss."}
      </p>
    </div>
  );
}
