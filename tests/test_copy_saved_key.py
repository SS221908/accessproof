"""Private key transfer checks; provider and macOS clipboard are mocked."""
import stat
from types import SimpleNamespace
from unittest.mock import Mock

from dotenv import dotenv_values
import pytest

from backend.credentials import api_key_summary
from scripts import copy_saved_key as helper


@pytest.fixture
def mac_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, "ROOT", tmp_path)
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    path = tmp_path / ".env"
    path.write_text("NEBIUS_API_KEY=synthetic-valid-secret\nNEBIUS_MODEL=nvidia/keep-this-model\n")
    return path


def fake_provider(monkeypatch, error=None):
    client = Mock()
    if error is not None:
        client.models.list.side_effect = error
    constructor = Mock(return_value=client)
    monkeypatch.setattr(helper, "OpenAI", constructor)
    return constructor, client


def test_cleanup_removes_only_whitespace_and_unicode_format_characters():
    candidate, cleaned = helper.prepare_key(" \tv1.ab\u200bc\ufeff.\nd_e-f=\u202e ")
    assert candidate == "v1.abc.d_e-f="
    assert cleaned is True
    candidate, cleaned = helper.prepare_key("  v1.abc.d_e-f=  ")
    assert candidate == "v1.abc.d_e-f="
    assert cleaned is False


@pytest.mark.parametrize("value", ["ab—cd", "ab…cd", "ａｂcd", "abécd", "ab\x00cd", "ab\x7fcd", "", None])
def test_unsupported_values_are_rejected_without_arbitrary_normalization(value):
    with pytest.raises(helper.KeyTransferError):
        helper.prepare_key(value)
    assert helper.prepare_key("ab.'\"-_=+/.cd")[0] == "ab.'\"-_=+/.cd"


def test_verified_transfer_preserves_settings_permissions_and_fingerprint(mac_environment, monkeypatch, capsys):
    constructor, client = fake_provider(monkeypatch)
    clipboard = Mock(side_effect=[SimpleNamespace(), SimpleNamespace(stdout="synthetic-valid-secret")])
    monkeypatch.setattr(helper.subprocess, "run", clipboard)
    assert helper.main([]) == 0
    constructor.assert_called_once_with(api_key="synthetic-valid-secret", base_url=helper.BASE_URL, timeout=20.0, max_retries=0)
    client.models.list.assert_called_once_with()
    client.close.assert_called_once_with()
    assert not client.chat.completions.create.called
    assert dotenv_values(mac_environment)["NEBIUS_MODEL"] == "nvidia/keep-this-model"
    assert stat.S_IMODE(mac_environment.stat().st_mode) == 0o600
    assert clipboard.call_args_list[0].args == (["pbcopy"],)
    assert clipboard.call_args_list[0].kwargs["input"] == "synthetic-valid-secret"
    assert clipboard.call_args_list[1].args == (["pbpaste"],)
    output = capsys.readouterr()
    assert api_key_summary("synthetic-valid-secret")["fingerprint"] in output.out
    assert "synthetic-valid-secret" not in output.out + output.err


def test_new_hidden_key_is_verified_before_save_or_copy(mac_environment, monkeypatch, capsys):
    incoming = "v1.new\u200bsecret.abc"
    candidate = "v1.newsecret.abc"
    entry = Mock(return_value=incoming)
    monkeypatch.setattr(helper, "getpass", entry)
    constructor, client = fake_provider(monkeypatch)
    original = mac_environment.read_text()
    clipboard = Mock(side_effect=[SimpleNamespace(), SimpleNamespace(stdout=candidate)])
    monkeypatch.setattr(helper.subprocess, "run", clipboard)

    def check_before_save():
        assert mac_environment.read_text() == original
        assert not clipboard.called

    client.models.list.side_effect = check_before_save
    assert helper.main(["--new"]) == 0
    entry.assert_called_once()
    assert constructor.call_args.kwargs["api_key"] == candidate
    assert dotenv_values(mac_environment)["NEBIUS_API_KEY"] == candidate
    output = capsys.readouterr()
    assert candidate not in output.out + output.err


@pytest.mark.parametrize("status", [401, 403, None])
def test_provider_failure_never_saves_or_copies_and_never_prints_provider_body(mac_environment, monkeypatch, capsys, status):
    error = ConnectionError("SECRET_KEY and RAW_PROVIDER_BODY")
    if status is not None:
        error.status_code = status
    _, client = fake_provider(monkeypatch, error)
    clipboard = Mock()
    monkeypatch.setattr(helper.subprocess, "run", clipboard)
    original = mac_environment.read_text()
    assert helper.main([]) == 1
    assert mac_environment.read_text() == original
    clipboard.assert_not_called()
    client.close.assert_called_once_with()
    output = capsys.readouterr()
    assert (f"HTTP {status}" if status is not None else "ConnectionError") in output.err
    if status in {401, 403}:
        assert "--new" in output.err
    else:
        assert "--new" not in output.err
        assert "retry this helper" in output.err
    assert "SECRET_KEY" not in output.out + output.err
    assert "RAW_PROVIDER_BODY" not in output.out + output.err


def test_invalid_saved_key_never_constructs_provider_or_touches_clipboard(mac_environment, monkeypatch, capsys):
    mac_environment.write_text("NEBIUS_API_KEY=v1.incomplete…value\n")
    constructor, _ = fake_provider(monkeypatch)
    clipboard = Mock()
    monkeypatch.setattr(helper.subprocess, "run", clipboard)
    original = mac_environment.read_text()
    assert helper.main([]) == 1
    constructor.assert_not_called()
    clipboard.assert_not_called()
    assert mac_environment.read_text() == original
    output = capsys.readouterr()
    assert "--new" in output.err
    assert "incomplete" not in output.out + output.err


def test_clipboard_mismatch_reports_failure_without_exposing_either_value(mac_environment, monkeypatch, capsys):
    fake_provider(monkeypatch)
    clipboard = Mock(side_effect=[SimpleNamespace(), SimpleNamespace(stdout="different-private-value")])
    monkeypatch.setattr(helper.subprocess, "run", clipboard)
    assert helper.main([]) == 1
    output = capsys.readouterr()
    assert "clipboard verification did not match" in output.err
    assert "Do not paste into Render" in output.err
    assert "Fingerprint:" not in output.out
    assert "different-private-value" not in output.out + output.err
    assert "synthetic-valid-secret" not in output.out + output.err


def test_non_mac_guard_does_not_read_key_or_call_provider(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(helper, "ROOT", tmp_path)
    monkeypatch.setattr(helper.sys, "platform", "linux")
    constructor, _ = fake_provider(monkeypatch)
    assert helper.main([]) == 1
    constructor.assert_not_called()
    assert not (tmp_path / ".env").exists()
    assert "macOS" in capsys.readouterr().err
