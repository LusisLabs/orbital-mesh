import { Activity, AlertTriangle, ShieldCheck } from "lucide-react";

import { humanize } from "../../lib/format";

interface DecisionCardProps {
  decisionType: string | null | undefined;
  autonomyTier: string | null | undefined;
  context?: string | null;
}

type Tier = "autonomous" | "approval_required" | "escalated" | "unknown";

function resolveTier(raw: string | null | undefined): Tier {
  if (raw === "autonomous" || raw === "approval_required" || raw === "escalated") return raw;
  return "unknown";
}

function tierClass(tier: Tier): string {
  if (tier === "autonomous") return "tier-autonomous";
  if (tier === "approval_required") return "tier-approval-required";
  return "tier-escalated";
}

function tierIcon(tier: Tier) {
  if (tier === "autonomous") return <Activity size={16} />;
  if (tier === "approval_required") return <ShieldCheck size={16} />;
  return <AlertTriangle size={16} />;
}

function tierLabel(tier: Tier): string {
  if (tier === "autonomous") return "Autonomous";
  if (tier === "approval_required") return "Approval required";
  if (tier === "escalated") return "Escalated";
  return "Tier unknown";
}

export function DecisionCard({ decisionType, autonomyTier, context }: DecisionCardProps) {
  const tier = resolveTier(autonomyTier);

  return (
    <div className={`mesh-decision-card ${tierClass(tier)} mesh-row-enter`}>
      <div className="tier-icon">{tierIcon(tier)}</div>
      <div className="tier-body">
        <span className="tier-eyebrow">Decision</span>
        <span className="tier-headline">{decisionType ? humanize(decisionType) : "Awaiting decision"}</span>
        {context ? <span className="tier-sub">{context}</span> : null}
      </div>
      <span className="tier-badge">{tierLabel(tier)}</span>
    </div>
  );
}
