"""The copier scaffold: generation correctness + generated-project e2e."""
import subprocess
import sys


def test_generates_expected_tree(generate_project):
    dst = generate_project()
    for path in (
        "pyproject.toml", "main.py", "Dockerfile", ".env.example", "README.md",
        "conftest.py", "acme_tracker/__init__.py", "acme_tracker/handlers.py",
        "acme_tracker/configurations.py", "acme_tracker/client.py",
        "acme_tracker/transformers.py", "tests/test_handlers.py",
        ".copier-answers.yml",
    ):
        assert (dst / path).exists(), f"missing {path}"
    handlers = (dst / "acme_tracker" / "handlers.py").read_text()
    assert "@action.auth" in handlers
    assert "@action.pull" in handlers
    assert "@webhook" not in handlers  # include_webhook=False default


def test_webhook_variant(generate_project):
    dst = generate_project(include_webhook=True, include_pull=False)
    handlers = (dst / "acme_tracker" / "handlers.py").read_text()
    assert "@webhook" in handlers
    assert "@action.pull" not in handlers
    configurations = (dst / "acme_tracker" / "configurations.py").read_text()
    assert "AcmeTrackerWebhookPayload" in configurations
    for py in (dst / "acme_tracker").rglob("*.py"):
        compile(py.read_text(), str(py), "exec")


def test_generated_files_are_valid_python(generate_project):
    dst = generate_project(include_webhook=True)
    for py in dst.rglob("*.py"):
        compile(py.read_text(), str(py), "exec")


def test_generated_project_test_suite_passes(generate_project):
    """The end-to-end contract: a fresh scaffold's own tests pass using the
    installed library + its pytest plugin (fixtures with no conftest wiring)."""
    dst = generate_project()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=dst, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "2 passed" in result.stdout
