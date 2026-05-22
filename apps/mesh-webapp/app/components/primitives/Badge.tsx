import type { ReactNode } from "react";

import { cn } from "../../utils/cn";

type BadgeTone = "neutral" | "good" | "warn" | "bad";

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: BadgeTone }) {
  return <span className={cn("badge", `badge-${tone}`)}>{children}</span>;
}
