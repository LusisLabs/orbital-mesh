# Small Business Thesis

This document frames a small-business-facing narrative for the Mesh Intelligence direction, grounded in what the repository currently implements.

## Executive Summary

Small teams need incident remediation, operational steering, and repeatable workflows, but they do not have the staffing and safety posture to run unbounded automation. Mesh Intelligence is a control plane that turns remediation into a bounded, evaluation-gated, operator-steerable loop with audit-grade run memory.

The wedge is not "generic agents for everything". The wedge is closed-loop remediation with explicit gates and explicit rollback semantics.

## Problem

Small businesses and small engineering teams face the same core issue:

- signals are fragmented
- remediation is tribal knowledge
- runbooks are inconsistent
- automation is either too weak or too risky
- evidence is scattered across logs and chats

## Solution Shape

Mesh Intelligence is a control plane between signals and actions:

- signals in (fixtures, custom JSON, live Kubernetes harvest)
- bounded decisions out (feature flags, incidents, Kubernetes rollouts)
- evaluation before execution
- operator steering by default
- artifacts, vault mirror, and Merkle audit surfaces

## Reality Check (Repository-Grounded)

This repo is strongest as a bounded remediation control plane with a browser operator surface. It is not yet a full SMB "virtual workforce" product.

What is implemented:

- stage machine: ingest -> trigger -> decision -> evaluation -> gate -> execution -> feedback
- steering commands and approval gates
- vault mirroring and Merkle proofs for run events
- native and CLI-backed integration modes with explicit readiness reporting
- production-like local Kubernetes e2e runbook

What requires additional product proof:

- guided vertical onboarding and templates
- role-based agent teams as a first-class product surface
- durable scheduling and cost controls for non-technical operators

## Initial Customer Wedges

- small SaaS teams: incident remediation workflow, bounded rollbacks, audit artifacts
- small agencies: operational playbooks, consistent evidence capture, client-facing incident summaries
- local businesses with simple ops: limited but high-trust workflows with approval gates

## Demo Plan

Preferred demo is the reproducible local Kubernetes loop:

- follow `docs/production-live-runbook.md`
- seed a bounded failure
- launch the run from the browser UI
- show evaluation and operator steering
- execute rollback/restart
- show artifacts, vault preview, and Merkle proof surfaces

## Roadmap (Near-Term)

Week-scale:

- publish an SMB demo scenario grounded in the existing operator loop
- capture one recording and screenshots for repeatability
- keep doc wording aligned with bounded remediation scope

Month-scale:

- tighten onboarding flows for a single vertical
- expand bounded actuation vocabulary without widening safety boundary
- improve evaluation gates and artifact discipline for stronger evidence
