from researchpilot import __version__
from researchpilot.cli import main


def test_help_exits_successfully(capsys) -> None:
    try:
        main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("--help did not exit")

    output = capsys.readouterr().out
    assert "local-first personal AI research assistant" in output


def test_version_exits_successfully(capsys) -> None:
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("--version did not exit")

    assert capsys.readouterr().out.strip() == f"researchpilot {__version__}"
