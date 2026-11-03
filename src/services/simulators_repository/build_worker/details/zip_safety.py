import io
import os
import zipfile

MAX_EXTRACTED_BYTES = 1 * 1024 * 1024 * 1024
MAX_FILES = 100_000


class ZipSafetyError(ValueError):
    pass


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    if info.create_system != 3:
        return False
    mode = info.external_attr >> 16
    return (mode & 0o170000) == 0o120000


def _safe_join(base_dir: str, member_name: str) -> str:
    normalized = os.path.normpath(member_name)
    if os.path.isabs(normalized) or normalized.startswith(".."):
        raise ZipSafetyError("Unsafe path in zip entry")
    target_path = os.path.join(base_dir, normalized)
    base_real = os.path.realpath(base_dir)
    target_real = os.path.realpath(target_path)
    if os.path.commonpath([base_real, target_real]) != base_real:
        raise ZipSafetyError("Zip entry escapes destination")
    return target_path


def unzip_bytes(zip_bytes: bytes, dest_dir: str) -> None:
    os.makedirs(dest_dir, exist_ok=True)
    total_bytes = 0
    files_count = 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zip_file:
        for info in zip_file.infolist():
            if info.is_dir():
                continue
            if _is_symlink(info):
                continue
            files_count += 1
            if files_count > MAX_FILES:
                raise ZipSafetyError("Zip exceeds max file count")
            total_bytes += info.file_size
            if total_bytes > MAX_EXTRACTED_BYTES:
                raise ZipSafetyError("Zip exceeds max total size")

            target_path = _safe_join(dest_dir, info.filename)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with zip_file.open(info) as src, open(target_path, "wb") as dst:
                dst.write(src.read())
