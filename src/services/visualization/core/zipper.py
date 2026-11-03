from __future__ import annotations

import zipfile
from io import BytesIO

from services.visualization.core.errors import CorruptedZipFile, NotAZipFile


class Zipper:
    def unzip(self, content: bytes) -> bytes:
        try:
            with zipfile.ZipFile(BytesIO(content), "r") as zf:
                bad = zf.testzip()
                if bad:
                    raise CorruptedZipFile(f"Corrupted ZIP file: {bad}")
                return zf.read(zf.namelist()[0])
        except zipfile.BadZipFile:
            raise NotAZipFile("Uploaded file is NOT a ZIP archive")
