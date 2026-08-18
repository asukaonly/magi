"""Authenticated streaming envelope for encrypted memory backups."""

from __future__ import annotations

import os
from pathlib import Path
import struct

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from .errors import MemoryPortabilityError

ENCRYPTED_BACKUP_MAGIC = b"MAGIBKP1"
_HEADER = struct.Struct(">8s16s12sIII")
_TAG_BYTES = 16
_KEY_BYTES = 32
_CHUNK_BYTES = 1024 * 1024
_ARGON2_MEMORY_KIB = 64 * 1024
_ARGON2_ITERATIONS = 3
_ARGON2_LANES = 4


def is_encrypted_backup(path: Path) -> bool:
    """Return whether *path* begins with the Magi encrypted envelope magic."""

    try:
        with Path(path).open("rb") as handle:
            return handle.read(len(ENCRYPTED_BACKUP_MAGIC)) == ENCRYPTED_BACKUP_MAGIC
    except OSError as exc:
        raise MemoryPortabilityError(
            "backup_unreadable",
            "The selected backup cannot be read.",
        ) from exc


def encrypt_backup_payload(source: Path, destination: Path, password: str) -> None:
    """Encrypt a ZIP payload with Argon2id-derived AES-256-GCM."""

    normalized_password = str(password)
    if not normalized_password:
        raise MemoryPortabilityError(
            "password_required",
            "A non-empty password is required for encrypted backup output.",
        )
    _validate_password(normalized_password)
    salt = os.urandom(16)
    nonce = os.urandom(12)
    header = _HEADER.pack(
        ENCRYPTED_BACKUP_MAGIC,
        salt,
        nonce,
        _ARGON2_MEMORY_KIB,
        _ARGON2_ITERATIONS,
        _ARGON2_LANES,
    )
    key = _derive_key(
        normalized_password,
        salt,
        _ARGON2_MEMORY_KIB,
        _ARGON2_ITERATIONS,
        _ARGON2_LANES,
    )
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header)

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        output_fd = os.open(destination, flags, 0o600)
        with Path(source).open("rb") as input_handle, os.fdopen(output_fd, "wb") as output_handle:
            output_handle.write(header)
            while chunk := input_handle.read(_CHUNK_BYTES):
                output_handle.write(encryptor.update(chunk))
            output_handle.write(encryptor.finalize())
            output_handle.write(encryptor.tag)
            output_handle.flush()
            os.fsync(output_handle.fileno())
    except FileExistsError as exc:
        raise MemoryPortabilityError(
            "output_exists",
            "The backup output path already exists.",
        ) from exc


def decrypt_backup_payload(source: Path, destination: Path, password: str) -> None:
    """Authenticate and decrypt an encrypted backup into a private ZIP payload."""

    normalized_password = str(password)
    if not normalized_password:
        raise MemoryPortabilityError(
            "password_required",
            "This backup is encrypted and requires its password.",
        )
    _validate_password(normalized_password)
    source = Path(source)
    try:
        source_size = source.stat().st_size
        with source.open("rb") as input_handle:
            raw_header = input_handle.read(_HEADER.size)
            if len(raw_header) != _HEADER.size:
                raise MemoryPortabilityError(
                    "backup_corrupt",
                    "The encrypted backup header is incomplete.",
                )
            magic, salt, nonce, memory_kib, iterations, lanes = _HEADER.unpack(raw_header)
            if magic != ENCRYPTED_BACKUP_MAGIC:
                raise MemoryPortabilityError(
                    "backup_format_invalid",
                    "The selected file is not an encrypted Magi memory backup.",
                )
            _validate_argon2_parameters(memory_kib, iterations, lanes)
            if source_size <= _HEADER.size + _TAG_BYTES:
                raise MemoryPortabilityError(
                    "backup_corrupt",
                    "The encrypted backup payload is incomplete.",
                )
            ciphertext_size = source_size - _HEADER.size - _TAG_BYTES
            input_handle.seek(source_size - _TAG_BYTES)
            tag = input_handle.read(_TAG_BYTES)
            input_handle.seek(_HEADER.size)

            key = _derive_key(
                normalized_password,
                salt,
                memory_kib,
                iterations,
                lanes,
            )
            decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
            decryptor.authenticate_additional_data(raw_header)
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            output_fd = os.open(destination, flags, 0o600)
            with os.fdopen(output_fd, "wb") as output_handle:
                remaining = ciphertext_size
                while remaining:
                    chunk = input_handle.read(min(_CHUNK_BYTES, remaining))
                    if not chunk:
                        raise MemoryPortabilityError(
                            "backup_corrupt",
                            "The encrypted backup payload is incomplete.",
                        )
                    remaining -= len(chunk)
                    output_handle.write(decryptor.update(chunk))
                output_handle.write(decryptor.finalize())
                output_handle.flush()
                os.fsync(output_handle.fileno())
    except InvalidTag as exc:
        _discard_partial(destination)
        raise MemoryPortabilityError(
            "password_or_integrity_invalid",
            "The password is incorrect or the backup has been modified.",
        ) from exc
    except FileExistsError as exc:
        raise MemoryPortabilityError(
            "output_exists",
            "The private restore staging path already exists.",
        ) from exc
    except MemoryPortabilityError:
        _discard_partial(destination)
        raise
    except OSError as exc:
        _discard_partial(destination)
        raise MemoryPortabilityError(
            "backup_unreadable",
            "The encrypted backup could not be read.",
        ) from exc


def _derive_key(
    password: str,
    salt: bytes,
    memory_kib: int,
    iterations: int,
    lanes: int,
) -> bytes:
    kdf = Argon2id(
        salt=salt,
        length=_KEY_BYTES,
        iterations=iterations,
        lanes=lanes,
        memory_cost=memory_kib,
        ad=None,
        secret=None,
    )
    return kdf.derive(password.encode("utf-8"))


def _validate_argon2_parameters(memory_kib: int, iterations: int, lanes: int) -> None:
    if (
        memory_kib != _ARGON2_MEMORY_KIB
        or iterations != _ARGON2_ITERATIONS
        or lanes != _ARGON2_LANES
    ):
        raise MemoryPortabilityError(
            "encryption_parameters_invalid",
            "The encrypted backup uses an unsupported key-derivation profile.",
        )


def _validate_password(password: str) -> None:
    if len(password.encode("utf-8")) > 1024:
        raise MemoryPortabilityError(
            "password_too_long",
            "The backup password must be at most 1024 UTF-8 bytes.",
        )


def _discard_partial(path: Path) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


__all__ = [
    "ENCRYPTED_BACKUP_MAGIC",
    "decrypt_backup_payload",
    "encrypt_backup_payload",
    "is_encrypted_backup",
]
