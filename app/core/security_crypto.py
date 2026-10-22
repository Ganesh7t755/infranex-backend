import os
import hmac
import hashlib
from typing import Tuple

ITERATIONS = 100000
ALGORITHM = "sha256"

def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    key = hashlib.pbkdf2_hmac(
        ALGORITHM,
        password.encode("utf-8"),
        bytes.fromhex(salt),
        ITERATIONS
    ).hex()
    return f"pbkdf2:{ALGORITHM}:{ITERATIONS}${salt}${key}"

def verify_password(plain_password: str, hashed_or_plain: str) -> bool:
    if not hashed_or_plain:
        return False

    if hashed_or_plain.startswith("pbkdf2:"):
        try:
            parts = hashed_or_plain.split("$")
            if len(parts) != 3:
                return False
            meta, salt_hex, key_hex = parts
            _, algo, iters_str = meta.split(":")
            iters = int(iters_str)

            candidate_key = hashlib.pbkdf2_hmac(
                algo,
                plain_password.encode("utf-8"),
                bytes.fromhex(salt_hex),
                iters
            ).hex()
            return hmac.compare_digest(candidate_key, key_hex)
        except Exception:
            return False

    # Backward-compatible fallback for dev/test environments with plain strings
    return hmac.compare_digest(plain_password, hashed_or_plain)
