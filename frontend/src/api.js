async function get(path) {
  const res = await fetch(path);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}

const q = (cutoff) => `?cutoff=${encodeURIComponent(cutoff)}`;

export const api = {
  meta: (cutoff) => get(`/api/meta${q(cutoff)}`),
  decision: (day, cutoff) => get(`/api/decision/${day}${q(cutoff)}`),
  summary: (cutoff) => get(`/api/accuracy/summary${q(cutoff)}`),
  daily: (cutoff) => get(`/api/accuracy/daily${q(cutoff)}`),
  byHour: (cutoff) => get(`/api/accuracy/by-hour${q(cutoff)}`),
  byHorizon: () => get(`/api/accuracy/by-horizon`),
  byLevel: (cutoff) => get(`/api/accuracy/by-level${q(cutoff)}`),
};

export const fmtMW = (v) => (v == null ? "n/a" : `${Math.round(v).toLocaleString("en-GB")} MW`);
export const fmtNum = (v, d = 0) => (v == null ? "n/a" : Number(v).toLocaleString("en-GB", { maximumFractionDigits: d }));