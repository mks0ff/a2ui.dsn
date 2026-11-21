import {useCallback, useEffect, useRef, useState, type FormEvent} from "react";
import {z} from "zod";
import {
  api, answerSchema, healthSchema, promptSchema, resolvePrompt, visualizationLabels,
  type Answer, type Card, type SuggestedPrompt, type Visualization,
} from "./api";
import {ResultCard} from "./ResultCard";

type Message = {id: number; question: string; answer?: Answer; error?: string};

function Icon({kind}: {kind: "agent" | "chart" | "people" | "shield" | "arrow"}) {
  const paths = {
    agent: "M8 3h8a5 5 0 0 1 5 5v3a5 5 0 0 1-5 5H8a5 5 0 0 1-5-5V8a5 5 0 0 1 5-5ZM8 9h.01M16 9h.01M9 20h6M3 20h1M20 20h1",
    chart: "M4 3v17h17M8 15v-5M13 15V6M18 15v-7",
    people: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M16 3a4 4 0 0 1 0 8M22 21v-2a4 4 0 0 0-3-3.87M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
    shield: "m12 3 8 4v5c0 5-8 9-8 9s-8-4-8-9V7l8-4ZM8 12l3 3 5-6",
    arrow: "M12 19V5M5 12l7-7 7 7",
  };
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[kind]} /></svg>;
}

export default function App() {
  const [prompts, setPrompts] = useState<SuggestedPrompt[]>([]);
  const [selected, setSelected] = useState<SuggestedPrompt | null>(null);
  const [parameters, setParameters] = useState<Record<string, string>>({});
  const [question, setQuestion] = useState("");
  const [visualization, setVisualization] = useState<Visualization>("auto");
  const [messages, setMessages] = useState<Message[]>([]);
  const [health, setHealth] = useState<z.infer<typeof healthSchema> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [followUpSource, setFollowUpSource] = useState("");
  const questionInput = useRef<HTMLTextAreaElement>(null);
  const canSubmit = ready && !busy && !!question.trim() && !health?.missing.length;

  useEffect(() => {
    Promise.all([api("/prompts"), api("/health"), api("/session", {method: "POST"})])
      .then(([catalog, status]) => {
        setPrompts(z.array(promptSchema).parse(catalog));
        setHealth(healthSchema.parse(status));
        setReady(true);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Serveur indisponible."));
  }, []);

  function choose(prompt: SuggestedPrompt) {
    setFollowUpSource("");
    const values = Object.fromEntries(prompt.parameters.map(parameter =>
      [parameter.id, parameter.default]));
    setSelected(prompt);
    setParameters(values);
    setQuestion(resolvePrompt(prompt, values));
    setVisualization(prompt.visualization);
  }

  const explore = useCallback((card: Card, establishment: string) => {
    const metrics: Record<string, string> = {
      payroll: "la masse salariale brute",
      headcount: "l'effectif en fin de mois (salaries distincts)",
      contributions: "les cotisations salariales, patronales et leur total explicite",
    };
    const metric = metrics[card.evidence.scope.metric];
    if (!metric) {
      setError("Cette mesure ne permet pas de preparer une question de suivi.");
      return;
    }
    setSelected(null);
    setFollowUpSource(`${card.title} / ${establishment}`);
    setQuestion(`Montre l'evolution mensuelle de ${metric} pour ${establishment} uniquement, ` +
      `sur les 12 mois se terminant au mois ${card.evidence.scope.end_month.slice(0, 7)}, ` +
      "dans la limite des mois disponibles.");
    setVisualization("line");
    setError("");
    questionInput.current?.focus();
    questionInput.current?.scrollIntoView?.({behavior: "smooth", block: "center"});
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || busy) return;
    const id = Date.now();
    const text = question.trim();
    setBusy(true);
    setError("");
    setMessages(previous => [...previous, {id, question: text}]);
    try {
      const answer = answerSchema.parse(await api("/analyze", {
        method: "POST", body: JSON.stringify({question: text, visualization}),
      }));
      setMessages(previous => previous.map(item => item.id === id ? {...item, answer} : item));
      setQuestion("");
      setSelected(null);
      setFollowUpSource("");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Analyse impossible.";
      setMessages(previous => previous.map(item => item.id === id ? {...item, error: message} : item));
    } finally { setBusy(false); }
  }

  async function clear() {
    setBusy(true);
    setError("");
    try {
      await api("/session", {method: "DELETE"});
      await api("/session", {method: "POST"});
      setMessages([]);
      setSelected(null);
      setFollowUpSource("");
      setQuestion("");
      setVisualization("auto");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Effacement impossible.");
    } finally { setBusy(false); }
  }

  return <div className="app-shell">
    <a className="skip-link" href="#main">Aller au contenu</a>
    <header className="topbar">
      <a className="brand" href="/" aria-label="DSN Atelier analytique">
        <Icon kind="agent" />
        <span><strong>DSN atelier</strong><small>Python ADK <span aria-hidden="true">&middot;</span> A2UI</small></span>
      </a>
      <details className="app-menu">
        <summary aria-label="Menu de l'application"><span aria-hidden="true">&#9776;</span></summary>
        <div className="menu-panel">
          <button className="new-conversation" disabled={busy || !ready} onClick={() => void clear()}>
            + Nouvelle conversation
          </button>
          <div className="dataset-note">
            <span className="badge">Donnees synthetiques</span>
            <p>1 employeur fictif, 3 etablissements et 24 mois de declarations.</p>
            <small>Analyses descriptives uniquement. Aucun avis de conformite.</small>
          </div>
        </div>
      </details>
    </header>
    <main id="main" className={messages.length ? "has-conversation" : ""}>
      <div className="workspace">
        {!messages.length && <section className="intro">
          <h1>Vos donnees prennent la parole.</h1>
          <p>Posez une question sur vos donnees sociales.<br />
            L'agent interroge BigQuery et A2UI dessine le resultat.</p>
        </section>}
        {error && <p className="error" role="alert">{error}</p>}
        {health && health.missing.length > 0 && <div className="notice" role="status">
          Le serveur est pret pour la configuration. Renseignez {health.missing.join(", ")} dans .env.
          Aucune requete cloud ne peut encore etre executee.
        </div>}
        {!messages.length && <section aria-label="Questions suggerees" className="suggestions">
          {prompts.map((prompt, index) => <button key={prompt.id}
            className={selected?.id === prompt.id ? "suggestion selected" : "suggestion"}
            aria-pressed={selected?.id === prompt.id}
            disabled={busy} onClick={() => choose(prompt)}>
            <span className="prompt-icon"><Icon kind={index % 3 === 0 ? "chart" : index % 3 === 1 ? "people" : "shield"} /></span>
            <span>{prompt.label}</span>
          </button>)}
        </section>}
        <section aria-label="Conversation" aria-live="polite" className="conversation">
          {messages.map(item => <article key={item.id} className="turn">
            <div className="user-question"><span>VOUS</span><p>{item.question}</p></div>
            {item.error && <p role="alert" className="error">{item.error}</p>}
            {item.answer && <>
              <p className="answer-text">{item.answer.text}</p>
              {item.answer.warnings.map((warning, index) =>
                <p className="notice" key={index}>Tentative precedente : {warning.message}</p>)}
              {item.answer.presentation && <ResultCard initial={item.answer.presentation}
                onExplore={explore} disabled={busy} />}
            </>}
            {!item.answer && !item.error && <p role="status" className="pending">
              L'agent examine la question et verifie les limites BigQuery...
            </p>}
          </article>)}
        </section>
        <form className="composer" onSubmit={event => void submit(event)}>
          <div className={selected || followUpSource ? "composer-heading" : "sr-only"}>
            <label htmlFor="question">{selected || followUpSource ? "Apercu editable" : "Votre question"}</label>
            {(selected || followUpSource) && <span>Aucune requete avant Analyser</span>}
          </div>
          {followUpSource && <p className="followup-source" role="status">Suivi de : {followUpSource}</p>}
          {selected && <div className="parameters">
            {selected.parameters.map(parameter => <label key={parameter.id}>
              {parameter.label}<input value={parameters[parameter.id] ?? ""}
                disabled={busy} onChange={event => {
                  const next = {...parameters, [parameter.id]: event.target.value};
                  setParameters(next);
                  setQuestion(resolvePrompt(selected, next));
                }} />
            </label>)}
          </div>}
          <textarea ref={questionInput} id="question" value={question} maxLength={4000} disabled={busy}
            placeholder="Posez une question, comme l'evolution de la masse salariale..."
            aria-describedby="composer-help"
            onKeyDown={event => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                if (canSubmit) event.currentTarget.form?.requestSubmit();
              }
            }}
            onChange={event => setQuestion(event.target.value)} rows={2} />
          <div className="composer-bottom">
            <label><Icon kind="chart" /><span className="sr-only">Visualisation</span>
              <select value={visualization} disabled={busy}
                onChange={event => setVisualization(event.target.value as Visualization)}>
                {Object.entries(visualizationLabels).map(([kind, label]) =>
                  <option key={kind} value={kind}>{label}</option>)}
              </select>
            </label>
            <div className="composer-actions">
              <span className="engine-label"><span aria-hidden="true">&#10022;</span> ADK + BigQuery</span>
              <button type="submit" className="primary" title="Analyser" disabled={!canSubmit}>
                <span className="sr-only">{busy ? "Analyse en cours..." : "Analyser"}</span><Icon kind="arrow" />
              </button>
            </div>
          </div>
        </form>
        <p className="composer-help" id="composer-help">Entree pour analyser. Maj + Entree pour une nouvelle ligne.</p>
        <p className="limits">
          Lecture seule &middot; {health?.limits.rows.toLocaleString("fr-FR") ?? "10 000"} lignes
          &middot; {health?.limits.chart_points.toLocaleString("fr-FR") ?? "5 000"} points par graphique
          &middot; {health ? Math.round(health.limits.bytes_billed / 1024 / 1024) : 100} MiB par requete
        </p>
        <p className="privacy">Conversation et resultats conserves en memoire du serveur local uniquement.
          Effacer la conversation ne supprime pas l'historique Google Cloud.</p>
      </div>
    </main>
  </div>;
}
