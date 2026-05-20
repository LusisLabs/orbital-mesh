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
        <i className="mesh-bar-grow" style={{ width: `${widthPct}%`, background: point.tone }} />
      </div>
      <strong>{widthPct}%</strong>
      <small>{point.detail}</small>
    </div>
  );
}
