import os
import time
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from pulse import cli
from pulse.cleanup.executor import execute_cleanup
from pulse.cleanup.planner import create_cleanup_plan
from pulse.cleanup.policies import POLICIES, recognized_path
from pulse.cleanup.recovery import prepare_recovery, recover_file

CASES = (
    ("npm-content", Path("ab/cd") / ("0" * 124)),
    ("go-build", Path("ab") / ("ab" + "0" * 62 + "-d")),
    ("cargo-downloads", Path("index.crates.io-6f17d22bba15001f/serde-1.0.200.crate")),
)


@pytest.fixture(params=CASES, ids=[item[0] for item in CASES])
def old_cache(request, tmp_path):
    category, relative = request.param
    file = tmp_path / POLICIES[category].root / relative
    file.parent.mkdir(parents=True)
    file.write_bytes(b"disposable downloaded cache")
    os.utime(file, (time.time() - 31 * 86400,) * 2)
    return tmp_path, category, file


def test_new_category_dry_run_and_exact_deletion(old_cache):
    home, category, file = old_cache
    unrelated = file.parent / "credentials.json"
    unrelated.write_bytes(b"keep")
    os.utime(unrelated, (time.time() - 100 * 86400,) * 2)
    plan = create_cleanup_plan(home, category=category)
    assert plan.complete and len(plan.files) == 1
    assert execute_cleanup(plan, home=home).results[0].status == "would_delete"
    assert file.exists()
    report = execute_cleanup(plan, dry_run=False, confirmed=True, home=home)
    assert report.results[0].status == "deleted" and not file.exists()
    assert unrelated.read_bytes() == b"keep"


def test_new_category_keeps_recent_or_hardlinked_files(old_cache):
    home, category, file = old_cache
    os.utime(file, None)
    assert not create_cleanup_plan(home, category=category).files
    os.utime(file, (time.time() - 31 * 86400,) * 2)
    os.link(file, file.parent / "other")
    assert not create_cleanup_plan(home, category=category).files


def test_new_category_recovery_and_mismatched_policy(old_cache, monkeypatch):
    from pulse.cleanup import executor

    home, category, file = old_cache
    plan = create_cleanup_plan(home, category=category)
    changed = replace(plan, category="pip-http")
    assert execute_cleanup(changed, dry_run=False, confirmed=True, home=home).blocked_reason
    assert file.exists()
    with monkeypatch.context() as context:
        context.setattr(executor.os, "unlink", Mock(side_effect=OSError("Cannot remove fixture")))
        report = execute_cleanup(plan, dry_run=False, confirmed=True, home=home)
    source = report.results[0].recovery_path
    assert source is not None
    recovery = prepare_recovery(source, file, home)
    assert recover_file(recovery, dry_run=False, confirmed=True, home=home).status == "restored"


@pytest.mark.parametrize(
    "category,path",
    [
        ("npm-content", "ab/cd/too-short"),
        ("go-build", "README"),
        ("go-build", "fuzz/interesting-input"),
        ("go-build", "cd/" + "ab" + "0" * 62 + "-d"),
        ("cargo-downloads", "private.example-6f17d22bba15001f/secret-1.0.0.crate"),
        ("cargo-downloads", "index.crates.io-6f17d22bba15001f/credentials.toml"),
    ],
)
def test_noncache_layouts_are_protected(category, path):
    assert not recognized_path(Path(path), category)


def test_new_category_cli_binds_selected_scope(old_cache, monkeypatch):
    home, category, file = old_cache
    monkeypatch.setattr(
        cli, "create_cleanup_plan", lambda **kwargs: create_cleanup_plan(home, **kwargs)
    )
    monkeypatch.setattr(
        cli, "execute_cleanup", lambda plan, **kwargs: execute_cleanup(plan, home=home, **kwargs)
    )
    result = CliRunner().invoke(cli.app, ["clean", "--category", category, "--dry-run"])
    assert result.exit_code == 0 and "would_delete=1" in result.stdout
    assert file.exists()


def test_cancelled_plan_cannot_delete(old_cache):
    home, category, file = old_cache
    cancel = Event()
    cancel.set()
    plan = create_cleanup_plan(home, category=category, cancel=cancel)
    assert not plan.complete
    assert execute_cleanup(plan, dry_run=False, confirmed=True, home=home).blocked_reason
    assert file.exists()
