"""localFiles must not expose secrets or destroy critical files.

It confined paths to the home root but within it allowed read/write/delete of
ANY file — including ~/.ssh, ~/.config/jarvis/config.json (API keys), and the
jarvis database. A prompt-injected or misrouted call could exfiltrate secrets
or destroy data. Deny dotfiles/dot-directories and the jarvis config + db, and
support an optional workspace root.
"""

from types import SimpleNamespace
from unittest.mock import Mock

from jarvis.tools.builtin.local_files import LocalFilesTool
from jarvis.tools.base import ToolContext


def _ctx(root, db_path):
    cfg = SimpleNamespace(db_path=str(db_path), local_files_root=str(root))
    return ToolContext(
        db=None, cfg=cfg, system_prompt="", original_prompt="",
        redacted_text="", max_retries=0, user_print=Mock(),
    )


def test_denies_dot_directory(tmp_path):
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "id_rsa").write_text("PRIVATE KEY")
    res = LocalFilesTool().run(
        {"operation": "read", "path": str(tmp_path / ".ssh" / "id_rsa")},
        _ctx(tmp_path, tmp_path / "jarvis.db"),
    )
    assert res.success is False
    assert "PRIVATE KEY" not in (res.reply_text or "")


def test_denies_dotfile(tmp_path):
    (tmp_path / ".env").write_text("SECRET=abc")
    res = LocalFilesTool().run(
        {"operation": "read", "path": str(tmp_path / ".env")},
        _ctx(tmp_path, tmp_path / "jarvis.db"),
    )
    assert res.success is False
    assert "SECRET=abc" not in (res.reply_text or "")


def test_denies_deleting_jarvis_db(tmp_path):
    db = tmp_path / "jarvis.db"
    db.write_text("the user's whole memory")
    res = LocalFilesTool().run(
        {"operation": "delete", "path": str(db)}, _ctx(tmp_path, db)
    )
    assert res.success is False
    assert db.exists()  # not deleted


def test_allows_normal_file_under_root(tmp_path):
    tool = LocalFilesTool()
    ctx = _ctx(tmp_path, tmp_path / "jarvis.db")
    w = tool.run({"operation": "write", "path": str(tmp_path / "notes.txt"), "content": "hi"}, ctx)
    assert w.success is True
    r = tool.run({"operation": "read", "path": str(tmp_path / "notes.txt")}, ctx)
    assert r.success is True
    assert "hi" in r.reply_text


def test_denies_path_outside_root(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    res = LocalFilesTool().run(
        {"operation": "read", "path": str(outside)}, _ctx(tmp_path, tmp_path / "jarvis.db")
    )
    assert res.success is False
