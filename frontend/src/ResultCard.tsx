import {createContext, useContext, useEffect, useMemo, useRef, useState} from "react";
import {A2uiSurface, createComponentImplementation, type ReactCatalogComponent} from "@a2ui/react";
import {Catalog, MessageProcessor, STRICT_VALIDATION} from "@a2ui/web_core";
import {CommonSchemas} from "@a2ui/web_core/v1_0";
import * as echarts from "echarts/core";
import {BarChart, LineChart} from "echarts/charts";
import {
  GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, AriaComponent,
} from "echarts/components";
import {CanvasRenderer} from "echarts/renderers";
import {z} from "zod";
import {
  api, formatCell, presentationSchema, rowSchema, visualizationLabels,
  type Card, type Presentation, type Visualization,
} from "./api";

echarts.use([
  BarChart, LineChart, GridComponent, TooltipComponent, LegendComponent,
  DataZoomComponent, AriaComponent, CanvasRenderer,
]);

const ResultContext = createContext<{
  card: Card;
  change: (kind: Visualization) => Promise<void>;
  busy: boolean;
} | null>(null);

function Plot({card}: {card: Card}) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current) return;
    const chart = echarts.init(element.current, undefined, {renderer: "canvas"});
    const money = card.evidence.scope.metric !== "headcount";
    const labels = card.rows.map(row => card.x
      ? formatCell(row[card.x], card.columns.find(c => c.name === card.x)?.type ?? "STRING")
      : "Periode selectionnee");
    chart.setOption({
      animation: false,
      aria: {enabled: true, description: `${card.title}. Le tableau detaille est disponible.`},
      color: ["#207363", "#ce8841", "#6775a2"],
      legend: {bottom: card.rows.length > 50 ? 50 : 0},
      grid: {left: 100, right: 24, top: 30, bottom: card.rows.length > 50 ? 110 : 85},
      tooltip: {
        trigger: "axis",
        renderMode: "richText",
        valueFormatter: (value: unknown) => formatCell(value, "NUMERIC", money),
      },
      xAxis: {type: "category", data: labels, axisLabel: {hideOverlap: true}},
      yAxis: {type: "value", axisLabel: {
        formatter: (value: number) => new Intl.NumberFormat("fr-FR", {
          notation: "compact", ...(money ? {style: "currency", currency: "EUR"} : {}),
        }).format(value),
      }},
      dataZoom: card.rows.length > 50 ? [{type: "inside"}, {type: "slider", bottom: 10}] : [],
      series: card.series.map(name => ({
        name, type: card.visualization, showSymbol: false,
        // All retained points are passed to ECharts; no sampling or aggregation.
        data: card.rows.map(row => row[name] == null ? null : Number(row[name])),
      })),
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [card]);
  return <div ref={element} className="plot" role="img" aria-label={card.title} />;
}

function ResultTable({card}: {card: Card}) {
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState(card.rows);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    setError("");
    if (offset === 0) { setPage(card.rows); setLoading(false); return; }
    const abort = new AbortController();
    setLoading(true);
    api(`/results/${card.result_id}/rows?offset=${offset}&limit=50`, {signal: abort.signal})
      .then(data => setPage(z.object({rows: z.array(rowSchema)}).parse(data).rows))
      .catch((err: unknown) => {
        if (!abort.signal.aborted) setError(err instanceof Error ? err.message : "Erreur de page.");
      })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [offset, card]);
  const money = card.evidence.scope.metric !== "headcount";
  return <>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="table-scroll" aria-busy={loading}>
      <table>
        <caption className="sr-only">{card.title} - resultat complet pagine</caption>
        <thead><tr>{card.columns.map(column => <th key={column.name}>{column.name}</th>)}</tr></thead>
        <tbody>{!loading && !error && page.map((row, i) => <tr key={offset + i}>
          {card.columns.map(column => <td key={column.name}>
            {formatCell(row[column.name], column.type, money && card.series.includes(column.name))}
          </td>)}
        </tr>)}</tbody>
      </table>
      {loading && <p role="status">Chargement de la page...</p>}
      {!card.row_count && <p>Aucune donnee pour cette selection.</p>}
    </div>
    <div className="pagination">
      <span>{card.row_count ? offset + 1 : 0}-{Math.min(offset + 50, card.row_count)} sur {
        card.row_count.toLocaleString("fr-FR")
      } lignes</span>
      <button disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - 50))}>
        Precedent
      </button>
      <button disabled={offset + 50 >= card.row_count || loading}
        onClick={() => setOffset(offset + 50)}>Suivant</button>
    </div>
  </>;
}

function TrustedResult({resultId}: {resultId: string}) {
  const context = useContext(ResultContext);
  if (!context || context.card.result_id !== resultId) {
    return <p role="alert">La liaison de donnees de cette carte est invalide.</p>;
  }
  const {card, change, busy} = context;
  const scope = card.evidence.scope;
  return <section className="result-card">
    <header className="card-header">
      <div><p className="eyebrow">RESULTAT BIGQUERY</p><h2>{card.title}</h2></div>
      <label className="visualization">Afficher en
        <select value={card.visualization} disabled={busy}
          onChange={event => void change(event.target.value as Visualization)}>
          {(["line", "bar", "table", "kpi"] as const).map(kind => <option
            key={kind} value={kind} disabled={card.options[kind] !== null}
            title={card.options[kind] ?? undefined}>{visualizationLabels[kind]}</option>)}
        </select>
      </label>
    </header>
    <div className="scope">
      <span>{scope.start_month.slice(0, 7)} / {scope.end_month.slice(0, 7)}</span>
      <span>{scope.establishment_ids.join(", ") || "Tous les etablissements"}</span>
      <span>{card.row_count.toLocaleString("fr-FR")} lignes completes</span>
    </div>
    {card.notice && <p className="notice" role="status">{card.notice}</p>}
    {card.visualization === "table" ? <ResultTable key={card.result_id} card={card} />
      : card.visualization === "kpi"
        ? <div className="kpi">
          <span>{card.series[0]}</span>
          <strong>{formatCell(
            card.rows[0][card.series[0]],
            card.columns.find(column => column.name === card.series[0])?.type ?? "NUMERIC",
            scope.metric !== "headcount",
          )}</strong>
        </div>
        : <Plot card={card} />}
    <details className="compatibility">
      <summary>Compatibilite des visualisations</summary>
      {Object.entries(card.options).map(([kind, reason]) =>
        <p key={kind}>{visualizationLabels[kind as Visualization]} : {reason ?? "Disponible"}</p>)}
    </details>
    <details className="evidence">
      <summary>SQL execute et sources</summary>
      <p>Job BigQuery : <code>{card.evidence.job_id}</code></p>
      <p>Sources : {card.evidence.sources.join(", ")}</p>
      <p>Octets traites : {card.evidence.bytes_processed.toLocaleString("fr-FR")}</p>
      <p>Filtres appliques : {scope.start_month} au {scope.end_month} ; {
        scope.establishment_ids.join(", ") || "tous les etablissements"
      }</p>
      <pre><code>{card.evidence.sql}</code></pre>
    </details>
  </section>;
}

const resultComponent = createComponentImplementation({
  name: "DSNResult",
  schema: z.object({resultId: CommonSchemas.DynamicString}),
}, ({props}) => <TrustedResult resultId={props.resultId} />);

const catalog = new Catalog("urn:dsn:catalog:v1", "1.0", [resultComponent]);

export function ResultCard({initial}: {initial: Presentation}) {
  const [presentation, setPresentation] = useState(initial);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const surfaceState = useMemo(() => {
    const processor = new MessageProcessor<ReactCatalogComponent>([catalog], undefined, {
      version: "1.0", validationConfig: STRICT_VALIDATION,
    });
    // This entry point validates unknown wire payloads before creating any UI.
    const errors = processor.processMessagesWithErrors(presentation.messages);
    return {surfaces: Array.from(processor.model.surfacesMap.values()), errors};
  }, [presentation.messages]);

  async function change(kind: Visualization) {
    setBusy(true);
    setError("");
    try {
      const next = presentationSchema.parse(await api(
        `/results/${presentation.card.result_id}?visualization=${encodeURIComponent(kind)}`,
      ));
      setPresentation(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Changement de representation impossible.");
    } finally { setBusy(false); }
  }

  return <ResultContext.Provider value={{card: presentation.card, change, busy}}>
    {error && <p role="alert" className="error">{error}</p>}
    {surfaceState.errors.length > 0
      ? <p role="alert" className="error">La surface A2UI a ete refusee par le validateur.</p>
      : surfaceState.surfaces.map(surface => <A2uiSurface key={surface.id} surface={surface} />)}
  </ResultContext.Provider>;
}
