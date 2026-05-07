from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class PqcSignatureProvider(Protocol):
    algorithm: str

    def sign(self, payload: dict[str, Any], *, key_id: str) -> dict[str, Any]:
        ...

    def verify(self, payload: dict[str, Any], proof: dict[str, Any]) -> bool:
        ...


class KemProvider(Protocol):
    algorithm: str

    def encapsulate(self, recipient_ref: str) -> dict[str, Any]:
        ...

    def decapsulate(self, encapsulated_key_ref: str) -> bytes:
        ...


class ZkDisclosureProvider(Protocol):
    statement_type: str

    def prove(self, statement: str, public_inputs: dict[str, Any], witness_ref: str) -> dict[str, Any]:
        ...

    def verify(self, proof: dict[str, Any], public_inputs: dict[str, Any]) -> bool:
        ...


@dataclass(frozen=True)
class CryptoProviderRegistry:
    pqc_signature: PqcSignatureProvider | None = None
    kem: KemProvider | None = None
    zk: ZkDisclosureProvider | None = None

    def require_pqc_signature(self) -> PqcSignatureProvider:
        if self.pqc_signature is None:
            raise NotImplementedError("PQC signature provider is not configured")
        return self.pqc_signature

    def require_kem(self) -> KemProvider:
        if self.kem is None:
            raise NotImplementedError("KEM provider is not configured")
        return self.kem

    def require_zk(self) -> ZkDisclosureProvider:
        if self.zk is None:
            raise NotImplementedError("ZK selective disclosure provider is not configured")
        return self.zk


def proposed_pqc_signature_proof() -> dict[str, Any]:
    return {
        "interface": "pqc_signature_v1",
        "algorithm": None,
        "key_id": None,
        "signature": None,
        "status": "proposed",
    }


def proposed_kem_proof() -> dict[str, Any]:
    return {
        "interface": "pqc_kem_v1",
        "algorithm": None,
        "encapsulated_key_ref": None,
        "status": "proposed",
    }


def proposed_zk_proof(*, run_id: str | None) -> dict[str, Any]:
    return {
        "hook": "selective_disclosure_v1",
        "statement": "Pilot packet can prove governance outcome without exposing raw reservoir contents.",
        "public_inputs": {
            "raw_sensitive_data_included": "false",
            "run_id": str(run_id),
        },
        "proof_ref": None,
        "status": "proposed",
    }
