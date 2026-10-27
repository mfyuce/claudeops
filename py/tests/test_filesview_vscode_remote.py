"""FilesView must not offer "open in VS Code" for remote-host sessions."""
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "webui/src/components/TerminalModal/FilesView.tsx").read_text()


def test_vscode_button_gated_on_local_host():
    assert 'const canOpenVscode = !host || host === "local"' in SRC
    assert "{canOpenVscode && <button" in SRC
    assert "onOpenVscode={canOpenVscode ?" in SRC
