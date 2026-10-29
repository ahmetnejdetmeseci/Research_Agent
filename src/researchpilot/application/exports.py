"""Provider-independent orchestration for exporting generated digests."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from researchpilot.domain import ExportDisposition
from researchpilot.domain.ports import DigestExporter, DigestReader


@dataclass(frozen=True)
class DigestExportResult:
    """Summary of one digest export operation."""

    path: str
    digest_id: str
    disposition: ExportDisposition


class ExportDigest:
    """Read one generated digest and send it through an exporter port."""

    def __init__(self, reader: DigestReader, exporter: DigestExporter) -> None:
        self._reader = reader
        self._exporter = exporter

    def execute(self, filename: str) -> DigestExportResult:
        """Export a generated digest without rebuilding or contacting services."""

        content = self._reader.read(filename)
        digest_id = hashlib.sha256(content.encode("utf-8")).hexdigest()
        receipt = self._exporter.export(filename, content)
        return DigestExportResult(
            path=receipt.path,
            digest_id=digest_id,
            disposition=receipt.disposition,
        )
