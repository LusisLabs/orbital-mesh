/**
 * One step in the "confidence movement" track on the RCA panel.
 *
 * The track tells a small story: as evidence accumulates, confidence
 * shifts. Animating the bar from 0% to its final width turns that
 * shift into a visible event rather than a static number — investor-
 * demo friendly without being theatrical.
 *
 * The ``tone`` field comes from the upstream ``ConfidencePoint``
 * struct in ``App.tsx``. Today it's a CSS color string; this
 * component does not translate it to a token because the upstream
 * code uses semantic tokens already (we replaced the hardcoded hex
 * inline in App.tsx during the same change set).
 */

export interface ConfidencePoint {
  id: string;
  label: string;
  value: number;
  detail: string;
  tone: string;
}

interface ConfidenceStepProps {
  point: ConfidencePoint;
}

export function ConfidenceStep({ point }: ConfidenceStepProps) {
  const widthPct = Math.round(point.value * 100);
  return (
    <div className="confidence-step mesh-row-enter mesh-row-enter-stagger">
      <span>{point.label}</span>
      <div className="confidence-track">
        <i
          className="mesh-bar-grow"
          style={{ width: `${widthPct}%`, background: point.tone }}
        />
      </div>
      <strong>{widthPct}%</strong>
      <small>{point.detail}</small>
    </div>
  );
}
