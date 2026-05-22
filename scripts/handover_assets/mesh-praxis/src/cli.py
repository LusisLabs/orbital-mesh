from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mesh_praxis._cli_util import emit, exit_code
from mesh_praxis._version import __version__
from mesh_praxis.praxis import (
    build_praxis_certification_binding,
    generate_praxis_mcp_contract,
    import_praxis_akto_security_evidence,
    load_praxis_source_bundle_fixture,
)
from mesh_praxis.verify_e2e import (
    build_proof_packet,
    verify_contracts,
    verify_managed_runtime_demo,
    verify_package_e2e,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mesh-praxis",
        description="Praxis source-to-MCP certification pipeline with bounded dry-run runtime.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("verify-e2e", help="Run contracts, proof packet, ingest, and runtime chain").add_argument("--json", action="store_true")
    sub.add_parser("verify-contracts", help="Validate bundled P1 contract fixtures").add_argument("--json", action="store_true")

    build = sub.add_parser("build-proof-packet", help="Emit the deterministic P8 proof packet")
    build.add_argument("--output", type=Path, default=None)
    build.add_argument("--json", action="store_true")

    demo = sub.add_parser("demo-pipeline", help="Run the demo source→contract→Akto→binding pipeline in memory")
    demo.add_argument("--json", action="store_true")

    runtime = sub.add_parser("demo-runtime", help="Run the bounded managed dry-run runtime chain")
    runtime.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "verify-e2e":
        payload = verify_package_e2e()
        payload["summary"] = "verify-e2e"
        emit(payload, json_mode=args.json)
        return exit_code(payload)

    if args.command == "verify-contracts":
        payload = verify_contracts()
        emit(payload, json_mode=args.json)
        return exit_code(payload)

    if args.command == "build-proof-packet":
        packet = build_proof_packet()
        text = json.dumps(packet, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        payload = {"status": "pass", "summary": "proof packet built", "packet_id": packet.get("packet_id"), "output": str(args.output) if args.output else None}
        if args.json:
            payload["packet"] = packet
        elif not args.output:
            print(text, end="")
        emit(payload, json_mode=args.json and args.output is not None)
        return 0 if packet.get("status") == "complete" else 1

    if args.command == "demo-pipeline":
        source_bundle = load_praxis_source_bundle_fixture()
        generated = generate_praxis_mcp_contract(
            source_bundle=source_bundle,
            contract_id="praxis-cli-demo-contract",
        )
        akto = import_praxis_akto_security_evidence(
            akto_result_path="fixtures/praxis/demo-akto-results.json",
            generated_contract=generated,
            evidence_id="praxis-cli-demo-akto",
        )
        binding = build_praxis_certification_binding(
            generated_contract=generated,
            akto_evidence=akto,
            binding_id="praxis-cli-demo-binding",
            connector_id="praxis-cli-demo-mcp",
            acp_session_id="praxis-cli-demo-acp",
        )
        payload = {
            "status": "pass",
            "summary": "demo pipeline complete",
            "source_packets": len(source_bundle["source_packets"]),
            "tool_candidates": len(generated["tool_candidates"]),
            "akto_findings": len(akto["findings"]),
            "certified_tools": len(
                [b for b in binding.get("tool_bindings", []) if b.get("certification_result") == "certified"]
            ),
            "connector_id": binding.get("connector_id"),
        }
        if args.json:
            payload["generated_contract"] = generated
            payload["certification_binding"] = binding
        emit(payload, json_mode=args.json)
        return 0

    if args.command == "demo-runtime":
        payload = verify_managed_runtime_demo()
        payload["summary"] = "managed dry-run runtime demo"
        emit(payload, json_mode=args.json)
        return exit_code(payload)

    print(f"unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
