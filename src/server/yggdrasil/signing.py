from __future__ import annotations

import base64
import os

from core.logger import colorize_log

from server.yggdrasil.state import STATE


__all__ = [
    "_get_private_key",
    "get_public_key_pem",
    "_sign_texture_property",
]


def _get_private_key():
    if STATE.private_key_cache is not None:
        return STATE.private_key_cache

    try:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        return None

    key_path = os.path.expanduser("~/.histolauncher/.yggdrasil_key")
    os.makedirs(os.path.dirname(key_path), exist_ok=True)

    if os.path.exists(key_path):
        try:
            with open(key_path, "rb") as key_file:
                STATE.private_key_cache = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None,
                    backend=default_backend(),
                )
                return STATE.private_key_cache
        except Exception as e:
            print(colorize_log(f"[yggdrasil] Failed to load existing key: {e}"))

    try:
        print(colorize_log(
            "[yggdrasil] Generating new 4096-bit RSA key for texture signing, "
            "this may take a moment..."
        ))
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
            backend=default_backend(),
        )
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with open(key_path, "wb") as key_file:
            key_file.write(pem)
        STATE.private_key_cache = private_key
        return STATE.private_key_cache
    except Exception as e:
        print(colorize_log(f"[yggdrasil] Failed to generate key: {e}"))
        return None


def get_public_key_pem() -> str | None:
    private_key = _get_private_key()
    if not private_key:
        return None
    try:
        from cryptography.hazmat.primitives import serialization

        pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return pem.decode("utf-8")
    except Exception as e:
        print(colorize_log(f"[yggdrasil] Failed to get public key: {e}"))
        return None


def _sign_texture_property(encoded_value: str) -> str | None:
    private_key = _get_private_key()
    if not private_key:
        return None

    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        return None

    try:
        signature = private_key.sign(
            encoded_value.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA1(),
        )
        return base64.b64encode(signature).decode("utf-8")
    except Exception as e:
        print(colorize_log(f"[yggdrasil] Failed to sign texture property: {e}"))
        return None
