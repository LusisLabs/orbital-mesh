from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime import load_schema, validate_payload
from shared.mesh_runtime.ecs_fargate import verify_ecs_fargate_promotion_proof


class EcsFargatePromotionTests(unittest.TestCase):
    def test_ecs_fargate_promotion_schema_is_loadable(self) -> None:
        schema = load_schema("ecs-fargate-promotion-proof.schema.json")
        self.assertEqual(schema["title"], "EcsFargatePromotionProof")

    def test_ecs_fargate_promotion_proof_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ecs-fargate-promotion.json"
            payload = _proof()
            validate_payload("ecs-fargate-promotion-proof.schema.json", payload)
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = verify_ecs_fargate_promotion_proof(path)

        self.assertEqual(result["schema_version"], "mesh.ecs_fargate_promotion_verification.v1")
        self.assertEqual(result["status"], "pass")
        self.assertTrue(all(result["checks"].values()))

    def test_missing_feedback_blocks_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ecs-fargate-promotion.json"
            payload = _proof()
            payload["feedback"]["status"] = "missing"
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = verify_ecs_fargate_promotion_proof(path)

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["feedback_proved"])

    def test_raw_secret_material_blocks_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ecs-fargate-promotion.json"
            payload = _proof()
            payload["aws_account_boundary"]["raw_secret_material_present"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = verify_ecs_fargate_promotion_proof(path)

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["no_raw_secret_material"])

    def test_local_environment_blocks_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ecs-fargate-promotion.json"
            payload = _proof(environment="local")
            path.write_text(json.dumps(payload), encoding="utf-8")

            result = verify_ecs_fargate_promotion_proof(path)

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["nonlocal_environment"])

    def test_cli_verifies_promotion_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ecs-fargate-promotion.json"
            payload = _proof()
            path.write_text(json.dumps(payload), encoding="utf-8")

            process = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_ecs_fargate_promotion.py",
                    "--proof",
                    str(path),
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        result = json.loads(process.stdout)
        self.assertEqual(result["schema_version"], "mesh.ecs_fargate_promotion_verification.v1")
        self.assertEqual(result["status"], "pass")


def _proof(**overrides) -> dict:
    payload = {
        "schema_version": "mesh.ecs_fargate_promotion_proof.v1",
        "proof_id": "ecs_fargate_promotion_test",
        "generated_at": "2026-05-06T03:40:00Z",
        "operator_id": "platform@example.com",
        "target_id": "ecs_fargate",
        "environment": "pilot",
        "aws_account_boundary": {
            "account_id": "123456789012",
            "region": "us-east-1",
            "cluster_arn": "arn:aws:ecs:us-east-1:123456789012:cluster/orbital-mesh",
            "service_arn": "arn:aws:ecs:us-east-1:123456789012:service/orbital-mesh/mesh",
            "task_definition_arn": "arn:aws:ecs:us-east-1:123456789012:task-definition/orbital-mesh:42",
            "execution_role_arn": "arn:aws:iam::123456789012:role/orbital-mesh-execution",
            "task_role_arn": "arn:aws:iam::123456789012:role/orbital-mesh-task",
            "secret_refs": [
                "arn:aws:secretsmanager:us-east-1:123456789012:secret:mesh/database-url",
                "arn:aws:ssm:us-east-1:123456789012:parameter/mesh/policy-signing-key",
            ],
            "raw_secret_material_present": False,
            "public_ingress": False,
        },
        "image": {
            "tag": "123456789012.dkr.ecr.us-east-1.amazonaws.com/orbital-mesh:ci",
            "digest": f"sha256:{'a' * 64}",
        },
        "release_provenance": {
            "status": "complete",
            "packet_sha256": "b" * 64,
            "evidence_ref": "s3://mesh-release/provenance.json",
        },
        "health": {
            "status": "pass",
            "evidence_ref": "ecs-smoke://health/2026-05-06",
        },
        "readiness": {
            "status": "pass",
            "evidence_ref": "ecs-smoke://readiness/2026-05-06",
            "blockers": [],
        },
        "ingress_identity": {
            "tls_terminated": True,
            "sso_enforced": True,
            "mesh_headers_stripped": True,
            "operator_headers_stamped": True,
            "evidence_ref": "ecs-smoke://ingress/2026-05-06",
        },
        "persistence": {
            "state_backend": "postgres",
            "database_secret_ref": "arn:aws:secretsmanager:us-east-1:123456789012:secret:mesh/database-url",
            "restart_proof_ref": "postgres-restart://ecs-fargate/2026-05-06",
            "evidence_ref": "ecs-smoke://persistence/2026-05-06",
        },
        "feedback": {
            "status": "pass",
            "source": "prometheus",
            "evidence_ref": "ecs-smoke://feedback/2026-05-06",
        },
        "audit": {
            "status": "pass",
            "sink_ref": "audit-sink://ecs-fargate/2026-05-06",
            "evidence_ref": "ecs-smoke://audit/2026-05-06",
        },
        "rollback": {
            "status": "pass",
            "plan_ref": "rollback://ecs-service-force-new-deployment",
            "rehearsal_ref": "rollback-drill://ecs-fargate/2026-05-06",
            "evidence_ref": "ecs-smoke://rollback/2026-05-06",
        },
    }
    payload.update(overrides)
    return payload
