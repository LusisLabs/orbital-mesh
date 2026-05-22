import { NavLink } from "@remix-run/react";
import { Boxes, CheckCircle2, Database, LayoutDashboard, ShieldCheck } from "lucide-react";

const items = [
  { to: "/mesh", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/mesh/runs", label: "Runs", icon: Boxes },
  { to: "/mesh/approvals", label: "Approvals", icon: CheckCircle2 },
  { to: "/mesh/vault", label: "Vault", icon: Database },
  { to: "/mesh/policy", label: "Policy", icon: ShieldCheck }
];

export function SideNav() {
  return (
    <nav className="side-nav" aria-label="Mesh navigation">
      <div className="brand-lockup">
        <div className="brand-mark">M</div>
        <div>
          <strong>Orbital Mesh</strong>
          <span>Operator</span>
        </div>
      </div>
      <div className="nav-section">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}
              end={item.end}
              key={item.to}
              to={item.to}
            >
              <Icon aria-hidden="true" size={17} strokeWidth={1.8} />
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </div>
    </nav>
  );
}
