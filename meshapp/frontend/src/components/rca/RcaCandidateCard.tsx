import type { RcaGraphCandidate } from "../../lib/runGraph";

interface RcaCandidateCardProps {
  candidate: RcaGraphCandidate;
}

function formatPercent(value: number | null): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "unscored";
  const clamped = Math.max(0, Math.min(1, value));
  return `${Math.round(clamped * 100)}%`;
}

export function RcaCandidateCard({ candidate }: RcaCandidateCardProps) {
  const isTop = candidate.rank === 1;

  return (
    <article className={`rca-candidate-card mesh-row-enter mesh-row-enter-stagger${isTop ? " rca-candidate-top" : ""}`}>
      <div className="agent-attempt-header">
        <strong>
          #{candidate.rank} {candidate.cause}
        </strong>
        <span>{formatPercent(candidate.confidence)}</span>
      </div>
      {candidate.support.length > 0 ? <p>{candidate.support.slice(0, 4).join(", ")}</p> : null}
      {candidate.citationIds.length > 0 ? <code>{candidate.citationIds.slice(0, 4).join(" / ")}</code> : null}
    </article>
  );
}
