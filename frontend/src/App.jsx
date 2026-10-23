import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, AlertCircle, ArrowDownRight, ArrowUpRight, BarChart3, CheckCircle2,
  Clock3, Database, Download, ExternalLink, Gauge, RefreshCw, Wind,
} from 'lucide-react';
import {
  Bar, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { fetchAnalysis } from './services/api.js';

const DAY_OPTIONS = Array.from({ length: 31 }, (_, index) => {
  const day = String(index + 1).padStart(2, '0');
  return { value: `2026-01-${day}`, label: new Date(Date.UTC(2026, 0, index + 1)).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', timeZone: 'UTC' }) };
});
const CUTOFF_OPTIONS = Array.from({ length: 24 }, (_, hour) => `${String(hour).padStart(2, '0')}:00`).concat(['16:30', '17:30', '18:00', '19:00', '20:00', '21:00', '22:00', '23:00']).filter((value, index, all) => all.indexOf(value) === index).sort();

const fmt = (value, digits = 0) => value == null || !Number.isFinite(Number(value))
  ? '—'
  : Number(value).toLocaleString('en-GB', { maximumFractionDigits: digits, minimumFractionDigits: digits });
const fmtMetric = (value) => value == null ? '—' : fmt(value, 1);
const fmtDateTime = (value) => {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/London', timeZoneName: 'short' });
};

function MetricCard({ icon: Icon, label, value, unit, helper, tone = 'navy' }) {
  return (
    <article className="metric-card">
      <div className={`metric-icon ${tone}`}><Icon size={18} strokeWidth={2.1} /></div>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}<span>{unit}</span></div>
      <div className="metric-helper">{helper}</div>
    </article>
  );
}

function SectionTitle({ eyebrow, title, description, trailing }) {
  return (
    <div className="section-title-row">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {trailing}
    </div>
  );
}

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload ?? {};
  return (
    <div className="chart-tooltip">
      <strong>{label}</strong>
      <div className="tooltip-row"><span className="dot forecast-dot" />Forecast <b>{fmt(row.forecast_mw, 0)} MW</b></div>
      <div className="tooltip-row"><span className="dot actual-dot" />Actual <b>{fmt(row.actual_mw, 0)} MW</b></div>
      <div className="tooltip-divider" />
      <div className="tooltip-row"><span>Forecast error</span><b>{row.error_mw == null ? '—' : `${row.error_mw > 0 ? '+' : ''}${fmt(row.error_mw, 0)} MW`}</b></div>
      <div className="tooltip-published">Forecast published: {row.forecast_publish_time_display || 'No eligible forecast'}</div>
    </div>
  );
}

function EmptyChart({ title = 'No data to chart yet' }) {
  return <div className="empty-chart"><div className="empty-chart-icon"><BarChart3 size={24} /></div><strong>{title}</strong><span>When Elexon data is returned, the chart will appear here.</span></div>;
}

export default function App() {
  const [deliveryDate, setDeliveryDate] = useState('2026-01-14');
  const [cutoffTime, setCutoffTime] = useState('16:00');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async (force = false, signal) => {
    if (force) setRefreshing(true); else setLoading(true);
    setError('');
    try {
      const result = await fetchAnalysis({ date: deliveryDate, cutoffTime, refresh: force, signal });
      setData(result);
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message || 'Unable to load Elexon data.');
        setData(null);
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [deliveryDate, cutoffTime]);

  useEffect(() => {
    const controller = new AbortController();
    load(false, controller.signal);
    return () => controller.abort();
  }, [load]);

  const observations = data?.observations ?? [];
  const metrics = data?.metrics ?? {};
  const coverage = data?.coverage ?? {};
  const provenance = data?.provenance ?? {};
  const matchPercent = coverage.expected_intervals ? Math.round((coverage.matched_intervals / coverage.expected_intervals) * 100) : 0;
  const chartData = useMemo(() => observations.map((row) => ({ ...row, time: row.delivery_time, forecast: row.forecast_mw, actual: row.actual_mw, error: row.error_mw })), [observations]);

  const exportCsv = () => {
    if (!observations.length) return;
    const headers = ['delivery_date', 'delivery_period_start', 'forecast_publish_time', 'forecast_mw', 'actual_mw', 'error_mw', 'status'];
    const lines = [headers.join(','), ...observations.map((row) => [
      data.delivery_date, row.start_time, row.forecast_publish_time ?? '', row.forecast_mw ?? '', row.actual_mw ?? '', row.error_mw ?? '', row.status,
    ].map((value) => `"${String(value).replaceAll('"', '""')}"`).join(','))];
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `wind-forecast-${data.delivery_date}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark"><Wind size={23} strokeWidth={2.4} /></div>
          <div className="brand-name">Wind<span>Intel</span></div>
        </div>
        <div className="sidebar-kicker">WORKSPACE</div>
        <div className="side-link active"><Activity size={17} /><span>Forecast analysis</span><span className="side-active-dot" /></div>
        <div className="sidebar-kicker sidebar-kicker-spaced">DATA</div>
        <div className="side-link muted"><Database size={17} /><span>Source monitoring</span></div>
        <div className="sidebar-bottom">
          <div className="live-indicator"><span className="live-dot" /><span>Elexon API</span><b>Public</b></div>
          <div className="sidebar-footer">ANALYTICS ENVIRONMENT<br /><span>Historical review · Jan 2026</span></div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumbs"><span>Energy analytics</span><span className="crumb-slash">/</span><strong>Wind forecast</strong></div>
          <div className="topbar-right"><span className="topbar-period"><span className="period-dot" />JANUARY 2026 DATASET</span><span className="topbar-divider" /><span className="timezone-label"><Clock3 size={14} /> Europe/London</span></div>
        </header>

        <div className="page-wrap">
          <section className="page-intro">
            <div className="intro-copy">
              <div className="eyebrow">PROCUREMENT INTELLIGENCE <span className="eyebrow-line" /></div>
              <h1>Wind Forecast <span>Intelligence</span></h1>
              <p>Understand forecast accuracy before the market opens. Compare the forecast available at decision time against actual national wind generation.</p>
            </div>
            <div className="intro-badge"><div className="intro-badge-icon"><Gauge size={20} /></div><div><strong>Forecast performance</strong><span>Historical decision-time evaluation</span></div></div>
          </section>

          <section className="control-panel" aria-label="Analysis controls">
            <div className="control-title"><div className="control-heading-icon"><Activity size={18} /></div><div><strong>Analysis parameters</strong><span>Choose the delivery day and forecast decision cutoff.</span></div></div>
            <div className="control-fields">
              <label className="control-group"><span>DELIVERY DATE</span><select value={deliveryDate} onChange={(event) => setDeliveryDate(event.target.value)}>{DAY_OPTIONS.map((day) => <option key={day.value} value={day.value}>{day.value} · {day.label}</option>)}</select></label>
              <label className="control-group cutoff-control"><span>DECISION CUTOFF <span className="info-dot" title="Cutoff is interpreted on the previous day in Europe/London time.">i</span></span><select value={cutoffTime} onChange={(event) => setCutoffTime(event.target.value)}>{CUTOFF_OPTIONS.map((option) => <option key={option} value={option}>{option} UK time</option>)}</select></label>
              <button className="refresh-button" onClick={() => load(true)} disabled={loading || refreshing}><RefreshCw size={16} className={refreshing ? 'spin' : ''} />{refreshing ? 'Refreshing…' : 'Refresh data'}</button>
            </div>
            <div className="cutoff-note"><Clock3 size={13} /><span>Eligible forecast publications: <b>on or before {data?.cutoff_datetime ? fmtDateTime(data.cutoff_datetime) : `${new Date(new Date(`${deliveryDate}T00:00:00Z`).getTime() - 86400000).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' })} at ${cutoffTime} UK time`}</b>. Publications after this time are excluded.</span></div>
          </section>

          {error && (
            <div className="error-banner" role="alert"><div className="error-icon"><AlertCircle size={19} /></div><div className="error-text"><strong>Could not load live Elexon data</strong><p>{error}</p><span>No sample values are being displayed. Check your connection or retry once the API is reachable.</span></div><button onClick={() => load(true)} disabled={refreshing}><RefreshCw size={15} /> Retry</button></div>
          )}

          <div className="section-heading metrics-heading"><SectionTitle eyebrow="DAY AT A GLANCE" title="Forecast accuracy" description={loading && !data ? 'Retrieving the selected day from Elexon…' : 'All metrics use matched half-hour intervals with an eligible forecast.'} trailing={<div className="retrieval-state">{loading || refreshing ? <><span className="status-spinner" /> Updating</> : data ? <><CheckCircle2 size={15} /> Analysis loaded</> : <><AlertCircle size={15} /> Awaiting data</>}</div>} /></div>

          <section className="metric-grid">
            <MetricCard icon={Activity} label="Mean absolute error" value={fmtMetric(metrics.mae)} unit={metrics.mae == null ? '' : ' MW'} helper="Average magnitude of forecast error" tone="blue" />
            <MetricCard icon={Gauge} label="Root mean squared error" value={fmtMetric(metrics.rmse)} unit={metrics.rmse == null ? '' : ' MW'} helper="Penalizes larger misses more heavily" tone="violet" />
            <MetricCard icon={metrics.bias == null ? Activity : metrics.bias >= 0 ? ArrowUpRight : ArrowDownRight} label="Mean forecast bias" value={metrics.bias == null ? '—' : `${metrics.bias > 0 ? '+' : ''}${fmt(metrics.bias, 1)}`} unit={metrics.bias == null ? '' : ' MW'} helper={metrics.bias == null ? 'Unavailable without matched intervals' : metrics.bias > 0 ? 'Net overforecasting' : metrics.bias < 0 ? 'Net underforecasting' : 'No average directional bias'} tone={metrics.bias == null ? 'navy' : metrics.bias > 0 ? 'amber' : 'green'} />
            <article className="metric-card coverage-card">
              <div className="metric-topline"><div className="metric-icon teal"><CheckCircle2 size={18} /></div><span className="coverage-percent">{data ? `${matchPercent}%` : '—'}</span></div>
              <div className="metric-label">Interval coverage</div>
              <div className="metric-value coverage-value">{coverage.matched_intervals ?? '—'}<span> / 48</span></div>
              <div className="coverage-track"><span style={{ width: `${data ? matchPercent : 0}%` }} /></div>
              <div className="metric-helper">Valid forecast / actual pairs</div>
            </article>
          </section>

          <section className="chart-grid">
            <article className="panel main-chart-panel">
              <SectionTitle eyebrow="TIME SERIES" title="Forecast vs actual" description="National wind generation by half-hour delivery interval." trailing={<div className="chart-unit-pill">MW</div>} />
              {chartData.length ? <div className="chart-frame"><ResponsiveContainer width="100%" height="100%"><LineChart data={chartData} margin={{ top: 15, right: 12, left: 0, bottom: 4 }}>
                <CartesianGrid stroke="#eaf0f4" vertical={false} strokeDasharray="3 4" />
                <XAxis dataKey="time" tick={{ fill: '#8091a2', fontSize: 10 }} tickLine={false} axisLine={false} interval={5} minTickGap={18} />
                <YAxis tick={{ fill: '#8091a2', fontSize: 10 }} tickLine={false} axisLine={false} width={52} tickFormatter={(value) => fmt(value)} />
                <Tooltip content={<ChartTooltip />} />
                <Legend verticalAlign="top" align="right" iconType="circle" iconSize={7} wrapperStyle={{ fontSize: 11, paddingBottom: 14, color: '#566c80' }} />
                <Line name="Forecast" type="monotone" dataKey="forecast" stroke="#3578cb" strokeWidth={2.4} dot={false} activeDot={{ r: 4, strokeWidth: 0 }} connectNulls={false} />
                <Line name="Actual" type="monotone" dataKey="actual" stroke="#12a28b" strokeWidth={2.4} dot={false} activeDot={{ r: 4, strokeWidth: 0 }} connectNulls={false} />
              </LineChart></ResponsiveContainer></div> : <EmptyChart title={loading ? 'Loading generation series…' : 'No forecast / actual series'} />}
              <div className="chart-footnote"><span className="footnote-dot blue-dot" />Forecast vintage selected using the cutoff <span className="footnote-separator">·</span><span className="footnote-dot green-dot" />Actuals from FUELHH</div>
            </article>

            <article className="panel error-chart-panel">
              <SectionTitle eyebrow="ERROR DISTRIBUTION" title="Forecast error" description="Forecast minus actual, by delivery interval." trailing={<div className="chart-unit-pill">MW</div>} />
              <div className="error-legend"><span><i className="legend-swatch positive" />Overforecast</span><span><i className="legend-swatch negative" />Underforecast</span></div>
              {chartData.length ? <div className="error-chart-frame"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={chartData} margin={{ top: 12, right: 4, left: -6, bottom: 4 }}>
                <CartesianGrid stroke="#eaf0f4" vertical={false} strokeDasharray="3 4" />
                <XAxis dataKey="time" tick={{ fill: '#8091a2', fontSize: 10 }} tickLine={false} axisLine={false} interval={7} />
                <YAxis tick={{ fill: '#8091a2', fontSize: 10 }} tickLine={false} axisLine={false} width={48} tickFormatter={(value) => fmt(value)} />
                <ReferenceLine y={0} stroke="#8998a6" strokeWidth={1.2} />
                <Tooltip formatter={(value) => [value == null ? '—' : `${fmt(value, 0)} MW`, 'Error']} labelFormatter={(label) => `Delivery ${label}`} contentStyle={{ borderRadius: 9, border: '1px solid #e4ebf0', fontSize: 12 }} />
                <Bar dataKey="error" name="Forecast error" maxBarSize={12} radius={[2, 2, 0, 0]}>{chartData.map((entry, index) => <Cell key={`bar-${index}`} fill={entry.error == null ? '#d9e2ea' : entry.error >= 0 ? '#e5a044' : '#6a8ec8'} />)}</Bar>
              </ComposedChart></ResponsiveContainer></div> : <EmptyChart title={loading ? 'Loading error series…' : 'No error series'} />}
              <div className="error-explainer"><div className="explain-sign plus">+</div><div><b>Positive</b><span>Forecast above actual</span></div><div className="explain-sign minus">−</div><div><b>Negative</b><span>Forecast below actual</span></div></div>
            </article>
          </section>

          <section className="panel table-panel">
            <div className="table-panel-heading"><SectionTitle eyebrow="INTERVAL-LEVEL DETAIL" title="Delivery period breakdown" description="Each row is a 30-minute interval; missing observations stay blank." /><button className="export-button" onClick={exportCsv} disabled={!observations.length}><Download size={15} /> Export CSV</button></div>
            <div className="table-meta"><span><span className="small-live-dot" />{observations.length ? `${observations.length} intervals` : 'Waiting for records'}</span><span>Sorted by delivery time · local UK time</span></div>
            <div className="table-scroll"><table><thead><tr><th>DELIVERY TIME</th><th>FORECAST PUBLISHED</th><th className="numeric">FORECAST (MW)</th><th className="numeric">ACTUAL (MW)</th><th className="numeric">ERROR (MW)</th><th>DATA STATUS</th></tr></thead><tbody>
              {observations.length ? observations.map((row) => <tr key={row.start_time}><td><div className="time-cell"><span className="time-marker" />{row.delivery_time}</div><span className="subcell">{deliveryDate}</span></td><td className="published-cell">{row.forecast_publish_time_display || <span className="missing-value">No eligible forecast</span>}</td><td className="numeric value-cell">{fmt(row.forecast_mw)}</td><td className="numeric value-cell">{fmt(row.actual_mw)}</td><td className={`numeric error-value ${row.error_mw == null ? 'muted-value' : row.error_mw > 0 ? 'positive-value' : row.error_mw < 0 ? 'negative-value' : ''}`}>{row.error_mw == null ? '—' : `${row.error_mw > 0 ? '+' : ''}${fmt(row.error_mw)}`}</td><td><span className={`status-pill ${row.status === 'Matched' ? 'matched' : 'missing'}`}>{row.status === 'Matched' ? <CheckCircle2 size={12} /> : <AlertCircle size={12} />}{row.status}</span></td></tr>) : <tr><td colSpan="6" className="table-empty">{loading ? 'Retrieving records from the Elexon API…' : 'No records are available. Check the error message above and retry.'}</td></tr>}
            </tbody></table></div>
            <div className="table-footer"><span>Showing {observations.length ? `1–${observations.length}` : '0'} of 48 expected delivery periods</span><span>Missing values are not treated as zero</span></div>
          </section>

          <section className="provenance-grid">
            <article className="panel provenance-panel"><SectionTitle eyebrow="SOURCE TRACEABILITY" title="Data provenance" description="Data is fetched from the permitted Elexon sources only." />
              <div className="source-list">
                <div className="source-row"><div className="source-icon fuel"><Database size={17} /></div><div className="source-info"><strong>FUELHH</strong><span>Half-hourly generation outturn by fuel type · WIND</span><a href="https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream" target="_blank" rel="noreferrer">API documentation <ExternalLink size={11} /></a></div><span className="source-tag">Actual</span></div>
                <div className="source-row"><div className="source-icon wind"><Wind size={17} /></div><div className="source-info"><strong>WINDFOR</strong><span>Wind generation forecast · publication timestamp retained</span><a href="https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream" target="_blank" rel="noreferrer">API documentation <ExternalLink size={11} /></a></div><span className="source-tag forecast-tag">Forecast</span></div>
              </div>
              <div className="provenance-facts"><div><span>Last successful retrieval</span><strong>{provenance.retrieved_at ? fmtDateTime(provenance.retrieved_at) : '—'}</strong></div><div><span>Actual records fetched</span><strong>{provenance.actual_records_retrieved ?? '—'}</strong></div><div><span>Forecast records fetched</span><strong>{provenance.forecast_records_retrieved ?? '—'}</strong></div><div><span>Matched intervals</span><strong>{coverage.matched_intervals ?? '—'} / 48</strong></div></div>
            </article>
            <article className="panel methodology-panel"><SectionTitle eyebrow="METHOD NOTES" title="How to read this analysis" />
              <div className="method-note"><span className="method-number">01</span><div><strong>Decision-time forecast vintage</strong><p>For each delivery interval, the latest forecast published at or before the selected cutoff is used. Later publications are excluded.</p></div></div>
              <div className="method-note"><span className="method-number">02</span><div><strong>Error sign convention</strong><p>Error = forecast − actual. Positive values indicate overforecasting; negative values indicate underforecasting.</p></div></div>
              <div className="method-note"><span className="method-number">03</span><div><strong>Metrics use matched data only</strong><p>MAE, RMSE and bias are computed from intervals with both a selected forecast and a non-missing actual value.</p></div></div>
              <div className="assumption-callout"><Clock3 size={15} /><span><b>Cutoff assumption:</b> the chosen time is on the preceding day in Europe/London. 16:00 is a configurable demonstration default, not an asserted market deadline.</span></div>
            </article>
          </section>

          {provenance.warnings?.length > 0 && <section className="panel warning-panel"><div className="warning-heading"><AlertCircle size={17} /><strong>Data quality notes</strong><span>{provenance.warnings.length}</span></div><ul>{provenance.warnings.map((warning, index) => <li key={`${index}-${warning}`}>{warning}</li>)}</ul></section>}

          <footer className="page-footer"><span>WIND INTEL <span className="footer-dot">·</span> HISTORICAL ANALYTICS</span><span>Data source: Elexon Insights API <span className="footer-dot">·</span> January 2026 delivery dates only</span></footer>
        </div>
      </main>
    </div>
  );
}
