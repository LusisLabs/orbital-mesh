/**
 * Decision hero card — surfaces ``autonomy_tier`` as a glanceable
 * visual.
 *
 * Mesh's safety differentiation lives in the autonomy_tier field
 * (``autonomous`` / ``approval_required`` / ``escalated``). The
 * pre-polish UI buried this in a generic two-line stat. Investors
 * watching a demo of an "AI SRE" tool ask one question first:
 *
 *     "What stops the AI from doing something dumb?"
 *
 * This card answers that question in two seconds:
 *
 *   - color cascade tied to the tier (green / amber / red);
 *   - a badge with the tier name in monospace;
 *   - the decision_type spelled out (rollback_deployment, escalate, …);
 *   - one-line context (rationale or stage-summary).
 *
 * Pure presentation. The parent owns whether to show the card at all
 * (typically only after ``decision_ready`` has fired on the run).
 */

import { humanize } from "../../lib/format";
import { ShieldCheck, AlertTriangle, Activity } from "lucide-react";

interface DecisionCardProps {
  decisionType: string | null | undefined;
  autonomyTier: string | null | undefined;
  /**
   * One-line narrative. Typical sources: the decision summary or the
   * RCA report's likely_cause. Truncated by CSS; pass the long form
   * and let the layout handle it.
   */
  context?: string | null;
}

type Tier = "autonomous" | "approval_required" | "escalated" | "unknown";

function resolveTier(raw: string | null | undefined): Tier {
  // Defensive: schema allows ``autonomous`` / ``approval_required`` /
  // ``escalated`` per decision.schema.json, but the field is typed
  // ``string`` so a future addition wouldn't crash this card.
  if (raw === "autonomous" || raw === "approval_required" || raw === "escalated") {
    return raw;
  }
  return "unknown";
}

function tierClass(tier: Tier): string {
  if (tier === "autonomous") return "tier-autonomous";
  if (tier === "approval_required") return "tier-approval-required";
  if (tier === "escalated") return "tier-escalated";
  // Unknown tiers fall back to the escalated styling — conservative
  // default. The autonomy_tier is the safety floor; we'd rather show
  // red than green when we don't know what we're looking at.
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
        <span className="tier-headline">
          {decisionType ? humanize(decisionType) : "Awaiting decision"}
        </span>
        {context ? <span className="tier-sub">{context}</span> : null}
      </div>
      <span className="tier-badge">{tierLabel(tier)}</span>
    </div>
  );
}
