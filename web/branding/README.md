---
name: orbital-mesh-brand
description: Practical brand kit for Orbital Mesh operator surfaces.
version: 2.0.0
category: branding
owner: orbital-mesh team
state_slice: branding.brand_system.v1
---

# Orbital Mesh Brand Kit

State slice: `branding.brand_system.v1`.

This kit defines the visual and verbal system for Orbital Mesh: a private, policy-guided operator control plane for bounded remediation and model-lifecycle work. It is built for production operators, platform engineers, reliability teams, and security reviewers. The system should feel exact, durable, and auditable rather than promotional.

## Files

| File | Purpose |
|---|---|
| `logo.svg` | Primary transparent SVG mark. Use for repo badges, docs, UI chrome, and decks. |
| `mesh-tokens.css` | CSS custom properties and small utility classes for brand-aligned UI work. |
| `brand-guide.html` | Offline visual guide with palette, typography, mark rules, UI examples, and messaging rules. |

## Brand Architecture

| Level | Name | Use |
|---|---|---|
| Parent | Purna Labs | Company or lab-level context when needed. |
| Product | Orbital Mesh | Product, repository, docs, operator UI, and runtime surfaces. |
| Category frame | CROPS Mesh / AI CROPS | Cloud, Reliability, Ops, Platform, and Security capability framing. |

Do not rename packages, API routes, runtime schemas, or persisted artifacts as part of brand work unless a separate migration explicitly owns those state slices.

## Positioning

Use:

- policy-guided operator control plane
- bounded remediation
- private infrastructure automation
- operator-steerable runs
- evaluation-gated execution
- audit-ready run evidence
- CROPS: Cloud, Reliability, Ops, Platform, and Security

Avoid:

- self-healing
- autonomous production AI
- generic AI-powered claims
- protocol language unless a protocol contract is being documented
- superlatives that are not backed by measured evidence

## Visual Principles

1. Operational first. Dense, legible surfaces beat decorative hero treatment.
2. Status must be semantic. Green means approved or passed, amber means waiting or deferred, red means blocked or failed.
3. Proof has its own signal. Use proof cyan for Merkle roots, hashes, run exports, and signed evidence.
4. Agent and topology accents stay secondary. Purple is for topology/model-lifecycle context, not the primary brand.
5. Radius stays tight. Use 4px, 6px, and 8px. Avoid pill-heavy dashboards except for status chips.
6. Typography stays practical. System UI fonts are the default; monospace is reserved for IDs, hashes, stages, commands, and schemas.

## Logo

The mark shows six infrastructure nodes routed through a central policy gate. The broken orbital perimeter signals bounded authority and operator steering.

Usage:

- Minimum size: 24px UI icon, 48px docs/decks.
- Clearspace: at least half the mark width around all sides.
- Preferred background: `--om-color-bg` or `--om-color-surface`.
- Use the SVG unchanged for product identity.
- In very small UI contexts, use the existing Codicon `circuit-board` only when the full mark would lose clarity.

Do not:

- Add glow filters or animation to the mark in production UI.
- Recolor semantic green, warning, or danger states as brand decoration.
- Place the mark inside rounded blobs or marketing-style badges.
- Use the mark as a spinner for long-running remediation.

## Color System

| Token | Hex | Use |
|---|---|---|
| `--om-color-bg` | `#111217` | App and guide background |
| `--om-color-surface` | `#181A1F` | Panels, cards, sidebars |
| `--om-color-surface-raised` | `#20242C` | Raised controls and nested surfaces |
| `--om-color-border` | `#2C323D` | Default dividers |
| `--om-color-text` | `#F2F4F7` | Primary text |
| `--om-color-text-muted` | `#8C96A5` | Labels, quiet metadata |
| `--om-color-action` | `#548AF7` | Primary interactive action |
| `--om-color-proof` | `#2AACB8` | Merkle, proof, hashes, audit evidence |
| `--om-color-success` | `#73B00A` | Approved, pass, ready |
| `--om-color-warning` | `#E8A33E` | Awaiting operator, deferred, caution |
| `--om-color-danger` | `#F75464` | Blocked, failed, unsafe |
| `--om-color-topology` | `#A982C0` | Agent topology and model-lifecycle context |

## Typography

- Sans/display: `Inter`, `IBM Plex Sans`, `Segoe UI`, system UI fallback.
- Mono: `IBM Plex Mono`, `SFMono-Regular`, `ui-monospace`.
- Letter spacing: `0` for normal headings and body. Use `0.04em` only for short uppercase metadata.
- No viewport-scaled type. Keep operator surfaces stable across screen sizes.

## Practical Adoption

Import the tokens only where brand work is intended:

```css
@import "../branding/mesh-tokens.css";
```

For app surfaces, map the token names into the local design system rather than replacing unrelated variables in one broad patch. Mutations must name the state slice they touch: for example, `web.operator_console.theme.v1`, `docs.public_branding.v1`, or `branding.brand_system.v1`.

## Public Utility Classes

`mesh-tokens.css` includes small utility classes for docs, prototypes, and narrow UI migrations:

- `.om-brand-surface`
- `.om-wordmark`
- `.om-kicker`
- `.om-status-pill`

These are public utilities for brand examples. Production app code should prefer local component classes unless a shared brand utility is explicitly adopted.
