import styles from "./Landing.module.css";

export const APP_SIGN_IN_URL = "https://app.lusislabs.com/";

const proofRows = [
  ["Context", "Repository, runtime, ownership, and incident state resolved before action."],
  ["Decision", "Canary, pause, rollback, or hold paths stay bound to operator approval."],
  ["Memory", "Prior fixes, evidence, and residual risk remain attached to the next run."],
];

export default function Landing() {
  return (
    <main className={styles.page}>
      <section className={styles.hero} aria-labelledby="landing-title">
        <div className={styles.copy}>
          <p className={styles.eyebrow}>Lusis Labs</p>
          <h1 id="landing-title">The operating brain for production maintenance.</h1>
          <p className={styles.summary}>
            Mesh keeps deployment context, evidence, approvals, and maintenance memory in one governed operator surface.
          </p>
          <div className={styles.actions}>
            <a className={styles.primaryAction} href={APP_SIGN_IN_URL}>
              Enter app
            </a>
            <span className={styles.handoff}>Hosted sign-in runs on app.lusislabs.com</span>
          </div>
        </div>

        <div className={styles.signalPanel} aria-label="Mesh run proof preview">
          <div className={styles.panelHeader}>
            <span>RUN PROOF</span>
            <strong>12:08:04.781</strong>
          </div>
          <div className={styles.nodeMap}>
            <span />
            <span />
            <span />
            <span />
          </div>
          <div className={styles.proofRows}>
            {proofRows.map(([label, detail]) => (
              <div className={styles.proofRow} key={label}>
                <strong>{label}</strong>
                <p>{detail}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}
