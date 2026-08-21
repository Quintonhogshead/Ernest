"""Tests for the dashboard's .env reader/writer."""

import os

from ernest import envfile


def test_read_values_ignores_comments(tmp_path):
    p = os.path.join(tmp_path, ".env")
    open(p, "w").write("# a comment\nFOO=bar\n\nBAZ = qux \n")
    vals = envfile.read_values(p)
    assert vals == {"FOO": "bar", "BAZ": "qux"}


def test_read_missing_file(tmp_path):
    assert envfile.read_values(os.path.join(tmp_path, "none")) == {}


def test_write_updates_in_place_and_preserves_comments(tmp_path):
    p = os.path.join(tmp_path, ".env")
    open(p, "w").write("# header\nFOO=old\n# note\nBAR=keep\n")
    envfile.write_values(p, {"FOO": "new"})
    text = open(p).read()
    assert "FOO=new" in text
    assert "BAR=keep" in text
    assert "# header" in text and "# note" in text


def test_empty_update_leaves_secret_unchanged(tmp_path):
    p = os.path.join(tmp_path, ".env")
    open(p, "w").write("SECRET=abc123\n")
    envfile.write_values(p, {"SECRET": ""})  # blank field = keep
    assert envfile.read_values(p)["SECRET"] == "abc123"


def test_new_key_appended(tmp_path):
    p = os.path.join(tmp_path, ".env")
    open(p, "w").write("FOO=bar\n")
    envfile.write_values(p, {"NEWKEY": "v"})
    assert envfile.read_values(p)["NEWKEY"] == "v"
    assert envfile.read_values(p)["FOO"] == "bar"


def test_is_set(tmp_path):
    p = os.path.join(tmp_path, ".env")
    open(p, "w").write("HAVE=x\nEMPTY=\n")
    assert envfile.is_set(p, "HAVE") is True
    assert envfile.is_set(p, "EMPTY") is False
    assert envfile.is_set(p, "MISSING") is False


def test_write_sets_owner_only_perms(tmp_path):
    p = os.path.join(tmp_path, ".env")
    envfile.write_values(p, {"K": "v"})
    mode = os.stat(p).st_mode & 0o777
    assert mode == 0o600
