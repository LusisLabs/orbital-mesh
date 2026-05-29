import { memo, useCallback, useEffect, useRef, useState } from "react";

import AsciiFlowCanvas from "../../src/landing/AsciiFlowCanvas";
import FractureRingCanvas from "../../src/landing/FractureRingCanvas";
import styles from "./ProjectionScrollIntro.module.css";

export const APP_SIGN_IN_URL = "https://app.lusislabs.com/";

const runTimeline = [
  {
    detail: "A generated change arrives with repository context, release target, owning team, and production constraints attached.",
    label: "12:08:04.182",
    title: "Change understood",
  },
  {
    detail: "Service topology, cloud state, deploy metadata, runbooks, and incident history are resolved before any action is drafted.",
    label: "12:08:04.406",
    title: "Context handled",
  },
  {
    detail: "The brain proposes a canary pause with blast radius, verification steps, and rollback path already bound.",
    label: "12:08:04.781",
    title: "Path proposed",
  },
  {
    detail: "Approval, result, failure mode, and residual risk are written back for the next deployment or maintenance run.",
    label: "12:18:05.102",
    title: "Run remembered",
  },
];

const proofRows = [
  ["Context", "Repository, runtime, ownership, and incident state resolved before action."],
  ["Decision", "Canary, pause, rollback, or hold paths stay bound to operator approval."],
  ["Memory", "Prior fixes, evidence, and residual risk remain attached to the next run."],
];

const rubricItems = [
  {
    detail: "Not a prompt stuffed with logs. Repository diffs, ownership, infra state, deploy history, and runtime signals are normalized into one working picture.",
    title: "Context handling",
  },
  {
    detail: "Plans releases, canaries, pauses, rollbacks, and verification checks while keeping operator approval and blast radius explicit.",
    title: "Deployment control",
  },
  {
    detail: "Infra drift, recurring failures, stale runbooks, and prior fixes stay attached to the system instead of disappearing after a ticket closes.",
    title: "Maintenance memory",
  },
  {
    detail: "Every action has a scope, a stop condition, a rollback, and a receipt. The system remains steerable when production risk is real.",
    title: "Operator governed",
  },
];

const stackItems = [
  {
    detail: "Builds a durable picture from code changes, service maps, cloud resources, tickets, incidents, approvals, and runtime signals.",
    meta: "Python / React / SSE",
    tag: "Context",
    title: "Unified context",
  },
  {
    detail: "Turns a change into an execution plan: deploy, pause, rollback, verify, escalate, or hold when evidence is insufficient.",
    meta: "CI/CD / Cloud / Policy",
    tag: "Release",
    title: "Deployment brain",
  },
  {
    detail: "Keeps the maintenance burden visible after code ships: drift, capacity, config, dependency, and ownership gaps.",
    meta: "Infra / SRE / Runbooks",
    tag: "Maintenance",
    title: "Maintenance loop",
  },
  {
    detail: "Connects with the tools teams already run instead of forcing another isolated AI surface into the workflow.",
    meta: "Integrations / Audit / Demo",
    tag: "Operator UI",
    title: "Operator surface",
  },
];

type ProjectionScrollIntroProps = {
  onComplete?: () => void;
};

const ProjectionScrollIntro = ({ onComplete }: ProjectionScrollIntroProps): React.ReactElement => {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const completedRef = useRef(false);
  const [progress, setProgress] = useState(0);
  const [exiting, setExiting] = useState(false);

  const finishIntro = useCallback(() => {
    if (completedRef.current) return;
    completedRef.current = true;
    setExiting(true);
    if (onComplete) {
      window.setTimeout(onComplete, 460);
      return;
    }
    window.location.assign(APP_SIGN_IN_URL);
  }, [onComplete]);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    const prevOverflow = document.body.style.overflow;

    document.body.style.overflow = "hidden";
    if (reduce.matches) setProgress(1);

    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return undefined;

    const onScroll = (): void => {
      const max = el.scrollHeight - el.clientHeight;
      const nextProgress = max <= 0 ? 1 : el.scrollTop / max;
      setProgress(Math.max(0, Math.min(1, nextProgress)));
    };

    el.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => {
      el.removeEventListener("scroll", onScroll);
    };
  }, []);

  return (
    <main ref={scrollRef} className={`${styles.root} ${exiting ? styles.exiting : ""}`} aria-label="Lusis Mesh landing page">
      {onComplete ? (
        <button className={styles.skip} onClick={finishIntro} type="button">
          Enter demo
        </button>
      ) : null}

      <section className={styles.projectionHero}>
        <AsciiFlowCanvas progress={progress} />
        <FractureRingCanvas progress={progress} />
        <div className={styles.heroCopy} aria-label="Lusis Mesh introduction">
          <div>
            <p className={styles.eyebrow}>Lusis Mesh</p>
            <h1>A single brain for deployment and maintenance.</h1>
            <p className={styles.summary}>
              LLMs made code generation faster than the operational work around it. Lusis Mesh handles infrastructure, deployment,
              and production maintenance context so teams can ship with governed, inspectable action.
            </p>
            <div className={styles.heroActions}>
              <a className={`${styles.button} ${styles.primary}`} href={APP_SIGN_IN_URL}>
                Enter app
              </a>
              <a className={`${styles.button} ${styles.secondary}`} href="#proof">
                See how it works
              </a>
            </div>
          </div>
          <div aria-hidden="true" className={styles.signalRow}>
            <p className={styles.signalLabel}>Built for</p>
            <p>Teams shipping generated and human-written code into production while still owning uptime, rollbacks, cloud state, and roadmap pressure.</p>
          </div>
        </div>
      </section>

      <div className={styles.companyHub}>
        <section className={styles.productHero} id="praxis">
          <div>
            <p className={styles.eyebrow}>Lusis Mesh / Praxis</p>
            <h2>The operating nervous system after code is written.</h2>
            <p className={styles.lede}>
              Software teams have adopted LLM-powered code generation, but the hard work still piles up around releases, cloud
              configuration, reliability, and follow-through. Praxis is the Lusis Mesh entry point for a proactive nervous system that carries
              context across those surfaces and turns scattered operational state into governed action.
            </p>
            <div aria-label="What Praxis is" className={styles.answerGrid}>
              <article className={styles.answer}>
                <span>What</span>
                <p>A unified control brain for infrastructure, deployment, and production maintenance work.</p>
              </article>
              <article className={styles.answer}>
                <span>Who</span>
                <p>Software organizations using generated code without wanting every release to create more operations drag.</p>
              </article>
              <article className={styles.answer}>
                <span>Why</span>
                <p>The market has too many narrow AI tools and too little shared context. Teams need one system that knows the work end to end.</p>
              </article>
            </div>
          </div>
          <aside aria-label="Sample Praxis run timeline" className={styles.proofPanel}>
            <div className={styles.proofHeader}>
              <span className={styles.mono}>Run timeline</span>
              <span className={styles.status}>Action proposed</span>
            </div>
            <div className={styles.timeline}>
              {runTimeline.map(({ detail, label, title }) => (
                <div key={title} className={styles.event}>
                  <span className={styles.mono}>{label}</span>
                  <strong>{title}</strong>
                  <p>{detail}</p>
                </div>
              ))}
            </div>
            <div className={styles.proofSummary} aria-label="Mesh run proof preview">
              {proofRows.map(([label, detail]) => (
                <div className={styles.proofSummaryRow} key={label}>
                  <strong>{label}</strong>
                  <p>{detail}</p>
                </div>
              ))}
            </div>
          </aside>
        </section>

        <section id="proof">
          <p className={styles.kicker}>What this looks like in practice</p>
          <h2>The brain handles context before it touches infrastructure.</h2>
          <div className={styles.evidenceGrid}>
            <article className={styles.policy}>
              <span className={styles.tag}>Held in context</span>
              <h3>Praxis keeps change intent, runtime state, and ownership together.</h3>
              <pre>{`change:   generated checkout migration
service:  checkout-api / canary
owner:    payments-platform
runtime:  p99 latency rising, db pool saturating
history:  incident-2406 resolved by rollback`}</pre>
            </article>
            <article className={styles.receipt}>
              <div className={styles.receiptHeader}>
                <span className={styles.mono}>Next action</span>
                <span className={styles.status}>Drafted</span>
              </div>
              <div className={styles.receiptBody}>
                <div className={styles.hashRow}>
                  <span>Target</span>
                  <code>checkout-api / canary</code>
                </div>
                <div className={styles.hashRow}>
                  <span>Plan</span>
                  <code>pause rollout, verify pool pressure</code>
                </div>
                <div className={styles.hashRow}>
                  <span>Guardrail</span>
                  <code>rollback path ready before approval</code>
                </div>
              </div>
            </article>
            <article aria-label="Before and after incident path" className={styles.path}>
              <div className={styles.pathRow}>
                <span>Before</span>
                <strong>Fast code, slow operations</strong>
                <p>Generation accelerates the change, then teams still chase deploy safety, cloud state, ownership, and follow-up work across separate tools.</p>
              </div>
              <div className={styles.pathRow}>
                <span>With Praxis</span>
                <strong>Context joined, path selected</strong>
                <p>Praxis binds diff, service graph, live signals, runbooks, approvals, and rollback constraints before proposing the safest next step.</p>
              </div>
              <div className={styles.pathRow}>
                <span>After</span>
                <strong>Maintenance does not reset</strong>
                <p>The result, unresolved risk, and operator decision stay in memory so later releases inherit real production context.</p>
              </div>
            </article>
          </div>
        </section>

        <section>
          <p className={styles.kicker}>What the product must cover</p>
          <h2>The missing automation is around the lifecycle, not the prompt.</h2>
          <div className={styles.rubricGrid}>
            {rubricItems.map(({ detail, title }) => (
              <article key={title} className={styles.card}>
                <h3>{title}</h3>
                <p>{detail}</p>
              </article>
            ))}
          </div>
        </section>

        <section id="products">
          <p className={styles.kicker}>Lusis Mesh surface</p>
          <h2>One control plane over the tools teams already use.</h2>
          <div className={styles.stackGrid}>
            {stackItems.map(({ detail, meta, tag, title }) => (
              <article key={title} className={styles.product}>
                <span className={styles.tag}>{tag}</span>
                <h3>{title}</h3>
                <p>{detail}</p>
                <div className={styles.meta}>{meta}</div>
              </article>
            ))}
          </div>
        </section>

        <section aria-label="App handoff" className={styles.handoff}>
          <div>
            <p className={styles.kicker}>Workspace handoff</p>
            <h2>Step into the working app.</h2>
            <p>The landing page ends where the product surface begins: the control room for context, proposed runs, approvals, and evidence a team can inspect.</p>
          </div>
          <a className={styles.desktopButton} href={APP_SIGN_IN_URL}>
            Enter app
          </a>
        </section>
      </div>
    </main>
  );
};

export default memo(ProjectionScrollIntro);
