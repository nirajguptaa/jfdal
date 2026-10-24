import { useEffect, useMemo, useState } from "react";
import { ComposedChart, Line, Area, XAxis, YAxis, Tooltip, Legend, CartesianGrid, ResponsiveContainer } from "recharts";
import { api, fmtMW, fmtNum } from "../api.js";

const hhmm = (iso) =>
  new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" });
const stamp = (iso) =>
  new Date(iso).toLocaleString("en-GB", {
    weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/London",
  });

export default function DecisionView({ meta, cutoff }) {
  const days = meta.delivery_days;
  const [day, setDay] = useState(days[0]);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [showActual, setShowActual] = useState(false);
  const [showBand, setShowBand] = useState(true);
  const [showAdjusted, setShowAdjusted] = useState(false);

  useEffect(() => {
    if (!days.includes(day)) setDay(days[0]);
  }, [days]);

  useEffect(() => {
    setError(null);
    setData(null);
    api.decision(day, cutoff).then(setData).catch((e) => setError(e.message));
  }, [day, cutoff]);

  const rows = useMemo(
    () =>
      (data?.series || []).map((r) => ({
        t: hhmm(r.startTime),
        forecast: r.forecast,
        corrected: r.corrected,
        actual: r.actual,
        bandBase: r.band_low,
        bandRange: r.band_high != null ? r.band_high - r.band_low : null,
      })),
    [data]
  );

  const idx = days.indexOf(day);

  return (
    <section>
      <div className="controls">
        <button disabled={idx <= 0} onClick={() => setDay(days[idx - 1])}>←</button>
        <label>
          Delivery day
          <select value={day} onChange={(e) => setDay(e.target.value)}>
            {days.map((d) => (
              <option key={d} value={d}>
                {new Date(d).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })}
              </option>
            ))}
          </select>
        </label>
        <button disabled={idx >= days.length - 1} onClick={() => setDay(days[idx + 1])}>→</button>
        <label className="check"><input type="checkbox" checked={showBand} onChange={(e) => setShowBand(e.target.checked)} /> Show likely range</label>
        <label className="check"><input type="checkbox" checked={showAdjusted} onChange={(e) => setShowAdjusted(e.target.checked)} /> Show bias-corrected forecast</label>
        <label className="check"><input type="checkbox" checked={showActual} onChange={(e) => setShowActual(e.target.checked)} /> Show what actually happened (hindsight)</label>
      </div>

      {error && <div className="alert">{error}</div>}
      {!data && !error && <p className="muted">Loading…</p>}

      {data && (
        <>
          <p className="lead">
            Buying for <b>{day}</b>, deciding at <b>{cutoff}</b> on the day before. The newest forecast available was
            published {data.forecast_published_range[0] === data.forecast_published_range[1] ? (
              <>at <b>{stamp(data.forecast_published_range[0])}</b></>
            ) : (
              <>between <b>{stamp(data.forecast_published_range[0])}</b> and <b>{stamp(data.forecast_published_range[1])}</b></>
            )}. It has a point every {data.step_hours === 1 ? "hour" : `${Math.round(data.step_hours * 60)} minutes`}.
          </p>

          <div className="cards">
            <Card label="Average wind forecast" value={fmtMW(data.forecast_mean_mw)} />
            <Card label="Lowest point of the day" value={fmtMW(data.forecast_min_mw)} />
            <Card label="Highest point of the day" value={fmtMW(data.forecast_max_mw)} />
            <Card label="Forecast energy for the day" value={`${fmtNum(data.forecast_mwh)} MWh`} />
          </div>

          <div className="panel">
            <h2>Wind forecast through the day</h2>
            <ResponsiveContainer width="100%" height={380}>
              <ComposedChart data={rows} margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="t" interval={Math.max(0, Math.round(6 / (data.step_hours || 0.5)) - 1)} />
                <YAxis tickFormatter={(v) => `${Math.round(v / 1000)}k`} label={{ value: "MW", angle: -90, position: "insideLeft" }} />
                <Tooltip formatter={(v, n) => (n === "bandRange" ? null : [fmtMW(v), n])} />
                <Legend />
                {showBand && data.band && (
                  <>
                    <Area dataKey="bandBase" stackId="b" stroke="none" fill="transparent" legendType="none" isAnimationActive={false} />
                    <Area dataKey="bandRange" stackId="b" stroke="none" fill="#0b7285" fillOpacity={0.18} name="Likely range (90%)" isAnimationActive={false} />
                  </>
                )}
                <Line dataKey="forecast" name="Forecast at decision time" stroke="#0b7285" strokeWidth={2.5} dot={false} isAnimationActive={false} />
                {showAdjusted && data.correction && (
                  <Line dataKey="corrected" name="Bias-corrected forecast" stroke="#7048e8" strokeWidth={2} strokeDasharray="6 4" dot={false} isAnimationActive={false} />
                )}
                {showActual && <Line dataKey="actual" name="Actual" stroke="#e8590c" strokeWidth={2} dot={false} isAnimationActive={false} />}
              </ComposedChart>
            </ResponsiveContainer>
            {showAdjusted && data.correction && (
              <p className="muted">
                The corrected line takes {fmtMW(data.correction.bias_mw)} off the forecast, the average miss on the{" "}
                {data.correction.based_on_days} days whose results were already known at decision time. That is
                {" "}{fmtNum(data.corrected_mwh)} MWh for the day instead of {fmtNum(data.forecast_mwh)} MWh. The Accuracy
                tab shows how this would have performed.
              </p>
            )}
            {showAdjusted && !data.correction && (
              <p className="muted">No correction yet. It needs at least 3 days whose results were known at decision time.</p>
            )}
            {showBand && !data.band && (
              <p className="muted">
                No range yet. It needs at least 3 earlier days of forecast errors, and it never uses days after the one you are
                looking at.
              </p>
            )}
            {showBand && data.band && (
              <p className="muted">
                Range is the forecast shifted by the 5th and 95th percentile of errors seen on the {data.band.based_on_days} earlier
                days ({fmtMW(data.band.lower_offset_mw)} to +{fmtMW(data.band.upper_offset_mw)}).
              </p>
            )}
          </div>

          {showActual && data.metrics_for_day?.n > 0 && (
            <div className="panel">
              <h2>How this day turned out</h2>
              <div className="cards">
                <Card label="Average miss (MAE)" value={fmtMW(data.metrics_for_day.mae)} />
                <Card label="Bias (forecast − actual)" value={fmtMW(data.metrics_for_day.bias)} />
                <Card label="Worst over-forecast" value={fmtMW(data.metrics_for_day.max_over)} />
                <Card label="Worst under-forecast" value={fmtMW(data.metrics_for_day.max_under)} />
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function Card({ label, value }) {
  return (
    <div className="card">
      <div className="card-label">{label}</div>
      <div className="card-value">{value}</div>
    </div>
  );
}
