from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pulse import cli
from pulse.cleanup.executor import execute_cleanup
from pulse.cleanup.planner import CACHE_ROOTS, PIP_ROOT, create_cleanup_plan
from pulse.cleanup.recovery import prepare_recovery, recover_file


@pytest.fixture
def legacy_cache(cache_file: tuple[Path, Path]) -> tuple[Path, Path]:
    home, file = cache_file
    relative = file.relative_to(home / PIP_ROOT)
    root = home / CACHE_ROOTS["pip-http-legacy"]
    (home / PIP_ROOT).rename(root)
    return home, root / relative


def test_legacy_plan_and_cleanup_are_bound_to_selected_root(legacy_cache) -> None:
    home, file = legacy_cache
    plan = create_cleanup_plan(home, category="pip-http-legacy")
    assert plan.category == "pip-http-legacy"
    assert plan.root == home / CACHE_ROOTS["pip-http-legacy"]
    assert execute_cleanup(plan, home=home).results[0].status == "would_delete"
    report = execute_cleanup(plan, dry_run=False, confirmed=True, home=home)
    assert report.results[0].status == "deleted"
    assert not file.exists()


def test_unknown_category_and_mismatched_root_are_refused(cache_file) -> None:
    home, file = cache_file
    with pytest.raises(ValueError):
        create_cleanup_plan(home, category="documents")
    plan = replace(create_cleanup_plan(home), category="pip-http-legacy")
    report = execute_cleanup(plan, dry_run=False, confirmed=True, home=home)
    assert report.blocked_reason
    assert file.exists()


def test_legacy_cli_selects_legacy_plan(legacy_cache, monkeypatch) -> None:
    home, file = legacy_cache
    monkeypatch.setattr(
        cli, "create_cleanup_plan", lambda **kwargs: create_cleanup_plan(home, **kwargs)
    )
    monkeypatch.setattr(
        cli, "execute_cleanup", lambda plan, **kwargs: execute_cleanup(plan, home=home, **kwargs)
    )
    result = CliRunner().invoke(cli.app, ["clean", "--category", "pip-http-legacy", "--dry-run"])
    assert result.exit_code == 0
    assert "Category: pip-http-legacy" in result.output
    assert "would_delete=1" in result.output
    assert file.exists()


def test_legacy_recovery_uses_same_scope(legacy_cache, monkeypatch) -> None:
    from unittest.mock import Mock

    from pulse.cleanup import executor

    home, file = legacy_cache
    with monkeypatch.context() as patch:
        patch.setattr(executor.os, "unlink", Mock(side_effect=PermissionError("Denied")))
        report = execute_cleanup(
            create_cleanup_plan(home, category="pip-http-legacy"),
            dry_run=False,
            confirmed=True,
            home=home,
        )
    source = report.results[0].recovery_path
    assert source is not None
    plan = prepare_recovery(source, file, home)
    assert recover_file(plan, dry_run=False, confirmed=True, home=home).status == "restored"
    assert file.exists()
