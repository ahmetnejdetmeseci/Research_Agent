from pathlib import Path

import pytest

from researchpilot.application import ExportDigest
from researchpilot.domain import DigestExportReceipt, ExportDisposition
from researchpilot.exporters import ObsidianExportError, ObsidianExporter


class MemoryReader:
    def __init__(self, content: str) -> None:
        self.content = content
        self.filename: str | None = None

    def read(self, filename: str) -> str:
        self.filename = filename
        return self.content


class RecordingExporter:
    def __init__(self) -> None:
        self.filename: str | None = None
        self.content: str | None = None

    def export(self, filename: str, content: str) -> DigestExportReceipt:
        self.filename = filename
        self.content = content
        return DigestExportReceipt(
            path="vault/ResearchPilot/researchpilot-test.md",
            disposition=ExportDisposition.CREATED,
        )


def test_export_service_connects_reader_to_provider_independent_exporter() -> None:
    reader = MemoryReader("# Digest\n")
    exporter = RecordingExporter()

    result = ExportDigest(reader, exporter).execute("researchpilot-test.md")

    assert reader.filename == "researchpilot-test.md"
    assert exporter.filename == "researchpilot-test.md"
    assert exporter.content == "# Digest\n"
    assert result.path == "vault/ResearchPilot/researchpilot-test.md"
    assert result.disposition is ExportDisposition.CREATED
    assert len(result.digest_id) == 64


def test_obsidian_export_creates_then_reuses_identical_managed_note(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    exporter = ObsidianExporter(vault)

    created = exporter.export("researchpilot-test.md", "# Digest\n")
    note = vault / "ResearchPilot" / "researchpilot-test.md"
    first_content = note.read_text(encoding="utf-8")
    unchanged = exporter.export("researchpilot-test.md", "# Digest\n")

    assert created.disposition is ExportDisposition.CREATED
    assert unchanged.disposition is ExportDisposition.UNCHANGED
    assert created.path == unchanged.path == str(note.resolve())
    assert first_content.startswith(
        "<!-- researchpilot:managed-digest sha256="
    )
    assert first_content.endswith("# Digest\n")
    assert note.read_text(encoding="utf-8") == first_content


def test_obsidian_export_updates_only_managed_note(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    exporter = ObsidianExporter(vault, folder="ResearchPilot/Digests")
    filename = "researchpilot-test.md"
    exporter.export(filename, "# First digest\n")

    result = exporter.export(filename, "# Second digest\n")
    note = vault / "ResearchPilot" / "Digests" / filename

    assert result.disposition is ExportDisposition.UPDATED
    assert "# Second digest" in note.read_text(encoding="utf-8")
    assert "# First digest" not in note.read_text(encoding="utf-8")


def test_obsidian_export_refuses_unrelated_note_collision(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    target_directory = vault / "ResearchPilot"
    target_directory.mkdir(parents=True)
    note = target_directory / "researchpilot-test.md"
    note.write_text("# My personal note\n", encoding="utf-8")
    exporter = ObsidianExporter(vault)

    with pytest.raises(ObsidianExportError, match="unrelated Obsidian note"):
        exporter.export(note.name, "# Generated digest\n")

    assert note.read_text(encoding="utf-8") == "# My personal note\n"


@pytest.mark.parametrize(
    "folder",
    [
        ".",
        "../outside",
        "/absolute",
        "folder\\child",
        "folder//child",
        "C:drive",
    ],
)
def test_obsidian_export_rejects_unsafe_folder(folder: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="normalized relative POSIX path"):
        ObsidianExporter(tmp_path, folder=folder)


def test_obsidian_export_refuses_symbolic_link_inside_vault(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    (vault / "ResearchPilot").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ObsidianExportError, match="symbolic link"):
        ObsidianExporter(vault).export("researchpilot-test.md", "# Digest\n")

    assert list(outside.iterdir()) == []


def test_obsidian_export_requires_existing_vault(tmp_path: Path) -> None:
    missing = tmp_path / "missing-vault"

    with pytest.raises(ObsidianExportError, match="vault does not exist"):
        ObsidianExporter(missing).export("researchpilot-test.md", "# Digest\n")

    assert missing.exists() is False


def test_obsidian_export_rejects_unsafe_filename(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(ValueError, match="plain Markdown filename"):
        ObsidianExporter(vault).export("../personal.md", "# Digest\n")
