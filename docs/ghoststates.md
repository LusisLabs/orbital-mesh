# Ghost State Modular Privacy Architecture

## Overview

This document defines the modular privacy architecture that complements the holistic AI, MEC, and Hyperimpact companion specs.

The key claim is:

- the public system should not directly store or interpret the private state required for compute bidding, linguistic artifacts, encrypted evaluation traces, or private settlement inputs
- instead, the public system should store commitments, roots, reveal policies, and binding proofs
- a privacy execution environment maintains the encrypted underlying state and proves that its committed state remains consistent with public balances, public obligations, and published roots

This is the architectural bridge between:

- public consensus and settlement
- private execution and encrypted state
- syntax transcription across chains and runtimes
- linguistic artifacts that must retain structure without becoming publicly legible

## Philosophy

The same full-stack argument that applies to holistic AI applies here. A system is not made coherent by making its outputs sound human. It becomes coherent when its hidden and visible layers remain coupled under explicit rules.

Ghost state is the privacy analogue of that claim. The public system should not hallucinate private truth. It should only accept cryptographically bound views into private state.

That is why the architecture is modular:

- public consensus remains public
- private state remains private
- the bridge is a binding proof, not blind trust in a narrative

## Core Conflict: Public State vs Private State

The core technical problem is state mismatch.

### Public world

The public layer is account-like and settlement-oriented.

It sees:

- balances
- escrows
- reward roots
- market definitions
- published metrics
- governance artifacts

It wants:

- deterministic verification
- simple state transitions
- stable settlement semantics

### Private world

The private layer is note-like and execution-oriented.

It sees:

- encrypted compute bids
- encrypted prompts and context
- private device identity material
- private evaluation traces
- confidential policy drafts
- sealed linguistic artifacts

It wants:

- confidentiality
- selective reveal
- replay protection
- commitment binding

### Ghost state

Ghost state is the bridge.

The public system does not know the private state directly. It knows:

- a root
- a commitment
- a nullifier set
- a binding proof that public obligations and private claims remain consistent

This means the system can preserve privacy while maintaining solvency, consistency, and auditability.

## Modular Sidecar Architecture

The privacy layer should be a sovereign sidecar, not hardcoded application logic inside the public execution engine.

### Public layer

The public layer owns:

- consensus
- escrowed balances
- reward-root anchoring
- market definition and settlement state
- public metrics and governance references

### Privacy execution environment

The privacy execution environment owns:

- encrypted ghost state database
- note or UTXO-like private objects
- nullifier checks
- private bid and artifact validation
- reveal policies
- state-root generation

### Bridge objects

The bridge between public and private layers consists of:

- `GhostCommitment`
- `GhostStateRoot`
- `BindingProof`
- `NullifierProof`
- `TranscriptionPayload`

The public system accepts those objects as evidence of private-state correctness without learning the private content itself.

## Why Syntax Transcription and Linguistics Matter

This system is not only about private balances. It is also about private structured language.

The holistic AI and MEC stack routes:

- prompts
- context packs
- evaluator instructions
- experiment policies
- preference data
- critique traces
- reward explanations

These are linguistic artifacts with syntax, semantics, and ordering constraints.

If those artifacts are reduced to opaque blobs without transcription structure, the system loses:

- verifiable lineage
- meaning-preserving routing
- cross-runtime coherence
- policy continuity

Ghost-state transcription solves this by separating:

- public commitment to the existence, lineage, and order of a linguistic artifact
- private storage of the artifact’s actual content

This matters because syntax itself is operational.

Examples:

- a prompt template must preserve slot structure and policy bindings
- an evaluator trace must preserve the relationship between claim, evidence, and score
- a context pack must preserve the ordering and scope of instructions
- a governance proposal draft may need to prove existence and timestamp before public reveal

Ghost commitments let the system prove:

- this artifact existed
- it belonged to this workflow
- it was not replayed or replaced
- it can be revealed once under the right policy

without exposing the artifact prematurely.

## System Use Cases

### MEC compute bidding

Private bids can be committed before reveal so hubs can compare capacity and cost without instantly exposing bidder identity or full strategy.

### Private training artifacts

Devices can commit:

- adapter deltas
- evaluation traces
- preference records

before selective validation or reward adjudication.

### Hyperimpact metric publication

Some KPI or treasury inputs may need:

- delayed reveal
- sealed publication
- cross-system transcription

before settlement windows close.

### Research-governance flows

Experiment policies, review traces, or branch-advance materials can be committed privately and revealed later for audit.

## Trust Model Rollout

Ghost state should be architecturally present from phase 1, but the trust model should upgrade over time.

### Phase 1: Iron Sidecar

Goal:

- functional ghost-state architecture with centralized or federated software trust

Properties:

- software sidecar
- encrypted local database
- root publication
- commitment and reveal logic
- no hardware attestation requirement

This is the right place to stabilize:

- state machine correctness
- transcription semantics
- reveal rules
- API contracts

### Phase 2: Glass Enclave

Goal:

- hardware-backed ghost-state execution

Properties:

- TDX, SEV-SNP, or equivalent trusted execution
- enclave-generated keys
- remote attestation
- stronger guarantees around private-state handling

This improves the trust root without changing the public system’s conceptual model.

### Phase 3: Diamond Circuit

Goal:

- cryptographic trust rather than hardware-trust dependence

Properties:

- TEE-assisted or TEE-free proving
- zk-backed verification of traces or state transitions
- public verification of binding claims

The public layer does not need a hard fork of meaning to support these transitions. The sidecar trust model can evolve while the bridge objects remain conceptually stable.

## Threat Model

Ghost-state systems must explicitly defend against:

- replayed reveals
- fake commitments
- nullifier collisions or omissions
- transcription ambiguity
- binding mismatch between public balances and private state
- sealed-artifact substitution
- timing attacks around reveal windows

The mitigation strategy is:

- explicit commitment schemas
- nullifier enforcement
- one-time reveal rules
- typed transcription payloads
- binding proofs between public obligations and private roots
- timestamped publication windows

## Design Constraints

This repository does not currently implement this architecture.

The purpose of this document is to define the companion privacy model that the holistic AI, MEC, and Hyperimpact specs can depend on without pretending the implementation already exists.

That distinction matters:

- current repo truth: strict multiverse market skeleton and Hyperliquid tooling
- companion architecture truth: how privacy-preserving transcription and ghost-state semantics would integrate with the broader system

## Summary

Ghost state is integral because the system needs more than hidden balances. It needs private but bindable structure.

That includes:

- compute bids
- linguistic artifacts
- evaluation traces
- treasury and KPI inputs
- governance materials

The public layer should see commitments and roots. The private layer should see encrypted structure. The bridge should be cryptographic, typed, and upgradable.
