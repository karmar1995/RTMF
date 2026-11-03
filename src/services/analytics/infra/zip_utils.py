from __future__ import annotations

import io
import zipfile


def zip_string(content: str, file_name: str = "data.csv") -> bytes:
    """Return a zip archive containing one UTF-8 encoded text file."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(file_name, content.encode("utf-8"))
    return buffer.getvalue()


def unzip_string(data: bytes) -> str:
    """Return UTF-8 text from a zip archive containing exactly one regular file."""

    with zipfile.ZipFile(io.BytesIO(data), mode="r") as zf:
        names = [name for name in zf.namelist() if not name.endswith("/")]
        if not names:
            raise ValueError("Zip archive has no files")
        if len(names) > 1:
            raise ValueError("Zip archive has multiple files")
        return zf.read(names[0]).decode("utf-8")
