import base64
import hashlib
import struct
import unittest

from nacl.signing import SigningKey

import server


class TestTonProofSecurity(unittest.TestCase):
    def _sign_proof(self, signing_key: SigningKey, *, address_hash: bytes, domain: str, timestamp: int, payload: str) -> str:
        domain_bytes = domain.encode("utf-8")
        payload_bytes = payload.encode("utf-8")
        message = (
            b"ton-proof-item-v2/"
            + struct.pack(">i", 0)
            + address_hash
            + struct.pack("<I", len(domain_bytes))
            + domain_bytes
            + struct.pack("<Q", timestamp)
            + payload_bytes
        )
        msg_hash = hashlib.sha256(message).digest()
        signed = hashlib.sha256(b"\xff\xff" + b"ton-connect" + msg_hash).digest()
        return base64.b64encode(signing_key.sign(signed).signature).decode("ascii")

    def test_ton_proof_signature_verifies_valid_payload(self) -> None:
        signing_key = SigningKey(bytes(range(32)))
        address_hash = bytes(range(32, 64))
        domain = "giftmarketzone.com"
        timestamp = 1770000000
        payload = "challenge:test"
        ok, reason = server._verify_ton_proof_signature(  # noqa: SLF001
            address=f"0:{address_hash.hex()}",
            public_key=signing_key.verify_key.encode().hex(),
            domain=domain,
            timestamp=timestamp,
            payload=payload,
            signature=self._sign_proof(
                signing_key,
                address_hash=address_hash,
                domain=domain,
                timestamp=timestamp,
                payload=payload,
            ),
        )
        self.assertTrue(ok, reason)

    def test_ton_proof_signature_rejects_tampered_payload(self) -> None:
        signing_key = SigningKey(bytes(range(32)))
        address_hash = bytes(range(32, 64))
        signature = self._sign_proof(
            signing_key,
            address_hash=address_hash,
            domain="giftmarketzone.com",
            timestamp=1770000000,
            payload="challenge:test",
        )
        ok, reason = server._verify_ton_proof_signature(  # noqa: SLF001
            address=f"0:{address_hash.hex()}",
            public_key=signing_key.verify_key.encode().hex(),
            domain="giftmarketzone.com",
            timestamp=1770000000,
            payload="challenge:tampered",
            signature=signature,
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "ton_proof_signature_mismatch")

