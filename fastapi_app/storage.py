import base64
import binascii
import hashlib
import hmac
import json
import mimetypes
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4


LOCAL_STORAGE_ROOT = Path(__file__).resolve().parent / "storage"
DEFAULT_STORAGE_ROOT = "/app/uploads" if Path("/app").exists() else str(LOCAL_STORAGE_ROOT)
PUBLIC_ASSET_PATH = os.getenv("PUBLIC_ASSET_PATH", "/assets").strip() or "/assets"
STORAGE_ROOT = Path(os.getenv("STORAGE_ROOT", DEFAULT_STORAGE_ROOT)).resolve()
DEFAULT_SIGNED_URL_TTL_SECONDS = int(os.getenv("FILE_URL_TTL_SECONDS", "900"))
MAX_SIGNED_URL_TTL_SECONDS = int(os.getenv("FILE_URL_MAX_TTL_SECONDS", "86400"))
MAX_SINGLE_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(1024 * 1024 * 1024)))


def ensure_storage_root() -> Path:
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    return STORAGE_ROOT


def _get_signing_secret() -> bytes:
    secret = os.getenv("FILE_URL_SIGNING_SECRET") or os.getenv("APP_SECRET_KEY") or "dev-insecure-file-secret"
    return secret.encode("utf-8")


def _safe_suffix(filename: Optional[str], mime_type: Optional[str]) -> str:
    if filename:
        suffix = Path(filename).suffix
        if suffix:
            return suffix.lower()
    if mime_type:
        guessed = mimetypes.guess_extension(mime_type)
        if guessed:
            return guessed.lower()
    return ".bin"


def sanitize_filename(filename: Optional[str], default_stem: str = "file") -> str:
    if not filename:
        return default_stem
    candidate = Path(filename).name.strip().replace("\x00", "")
    if not candidate:
        return default_stem
    return candidate[:255]


def decode_base64_content(content_base64: str) -> bytes:
    try:
        return base64.b64decode(content_base64, validate=True)
    except binascii.Error as exc:
        raise ValueError("Invalid base64 content") from exc


def _resolve_relative_path(relative_path: str) -> Path:
    root = ensure_storage_root()
    full_path = (root / relative_path).resolve()
    try:
        full_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Resolved path escapes storage root") from exc
    return full_path


def write_managed_bytes(relative_path: str, content: bytes) -> tuple[Path, str, int]:
    full_path = _resolve_relative_path(relative_path)
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(content)
    checksum = hashlib.sha256(content).hexdigest()
    return full_path, checksum, len(content)


def store_upload_bytes(user_id: int, filename: Optional[str], content: bytes) -> tuple[str, str, int]:
    suffix = _safe_suffix(filename, None)
    relative_path = f"uploads/{user_id}/{uuid4().hex}{suffix}"
    _, checksum, size_bytes = write_managed_bytes(relative_path, content)
    return relative_path, checksum, size_bytes


def allocate_upload_path(owner_user_id: Optional[int], filename: Optional[str], mime_type: Optional[str], kind: str = "user_input") -> tuple[str, str]:
    suffix = _safe_suffix(filename, mime_type)
    safe_name = sanitize_filename(filename, default_stem=f"{kind}{suffix}")
    owner_segment = str(owner_user_id or "shared")
    if kind == "generation_output":
        relative_path = f"results/{owner_segment}/{uuid4().hex}{suffix}"
    else:
        relative_path = f"uploads/{owner_segment}/{uuid4().hex}{suffix}"
    return relative_path, safe_name


def copy_source_into_job(user_id: int, job_id: int, source_path: str, role: str, filename: Optional[str] = None) -> tuple[str, str, int]:
    source = Path(source_path)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    suffix = _safe_suffix(filename or source.name, mimetypes.guess_type(source.name)[0])
    relative_path = f"jobs/{user_id}/{job_id}/{role}{suffix}"
    full_path = _resolve_relative_path(relative_path)
    full_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, full_path)
    checksum = sha256_for_file(full_path)
    return relative_path, checksum, full_path.stat().st_size


def store_job_result_bytes(
    user_id: int,
    job_id: int,
    filename: Optional[str],
    content: bytes,
    mime_type: Optional[str] = None,
) -> tuple[str, str, int]:
    suffix = _safe_suffix(filename, mime_type)
    relative_path = f"jobs/{user_id}/{job_id}/output{suffix}"
    _, checksum, size_bytes = write_managed_bytes(relative_path, content)
    return relative_path, checksum, size_bytes


def sha256_for_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def write_stream_to_managed_file(relative_path: str, chunks, max_bytes: Optional[int] = None) -> tuple[Path, str, int]:
    full_path = _resolve_relative_path(relative_path)
    full_path.parent.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    total = 0
    with full_path.open("wb") as handle:
        for chunk in chunks:
            if not chunk:
                continue
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                handle.close()
                full_path.unlink(missing_ok=True)
                raise ValueError("Upload exceeds allowed size")
            digest.update(chunk)
            handle.write(chunk)
    return full_path, digest.hexdigest(), total


def _urlsafe_b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _urlsafe_b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_signed_token(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body_encoded = _urlsafe_b64encode(body)
    signature = hmac.new(_get_signing_secret(), body_encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{body_encoded}.{_urlsafe_b64encode(signature)}"


def verify_signed_token(token: str, expected_action: Optional[str] = None) -> dict[str, Any]:
    try:
        body_encoded, signature_encoded = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("Malformed token") from exc

    expected_signature = hmac.new(_get_signing_secret(), body_encoded.encode("ascii"), hashlib.sha256).digest()
    provided_signature = _urlsafe_b64decode(signature_encoded)
    if not hmac.compare_digest(expected_signature, provided_signature):
        raise ValueError("Invalid token signature")

    try:
        payload = json.loads(_urlsafe_b64decode(body_encoded))
    except (json.JSONDecodeError, binascii.Error) as exc:
        raise ValueError("Invalid token payload") from exc

    expires_at = int(payload.get("exp") or 0)
    now = int(datetime.now(timezone.utc).timestamp())
    if expires_at <= now:
        raise ValueError("Token has expired")
    if expected_action and payload.get("action") != expected_action:
        raise ValueError("Token action mismatch")
    return payload


def build_signed_url_payload(*, action: str, file_id: int, relative_path: str, ttl_seconds: Optional[int] = None, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    ttl = ttl_seconds or DEFAULT_SIGNED_URL_TTL_SECONDS
    ttl = max(1, min(ttl, MAX_SIGNED_URL_TTL_SECONDS))
    payload = {
        "action": action,
        "file_id": file_id,
        "path": relative_path,
        "exp": int((datetime.now(timezone.utc) + timedelta(seconds=ttl)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return payload


def build_internal_signed_url(path_prefix: str, payload: dict[str, Any]) -> tuple[str, datetime]:
    token = create_signed_token(payload)
    expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    return f"{path_prefix}/{token}", expires_at


def get_managed_file_path(relative_path: str) -> Path:
    return _resolve_relative_path(relative_path)


def get_download_media_type(filename: Optional[str], mime_type: Optional[str]) -> str:
    if mime_type:
        return mime_type
    guessed, _ = mimetypes.guess_type(filename or "")
    return guessed or "application/octet-stream"


def get_public_asset_url_path(relative_path: str) -> str:
    normalized_prefix = "/" + PUBLIC_ASSET_PATH.strip("/")
    return f"{normalized_prefix}/{relative_path.lstrip('/')}"
