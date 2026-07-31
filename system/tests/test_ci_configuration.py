from pathlib import Path

CI_WORKFLOW_PATH = Path(".github/workflows/ci.yml")


def read_ci_workflow() -> str:
    assert CI_WORKFLOW_PATH.exists(), f"CI workflow does not exist: {CI_WORKFLOW_PATH}"

    return CI_WORKFLOW_PATH.read_text(
        encoding="utf-8",
    )


def test_ci_measures_authentication_coverage():
    workflow = read_ci_workflow()

    assert "--cov=accounts" in workflow
    assert "--cov=authentication" in workflow
    assert "--cov=sports" in workflow
    assert "--cov=system" in workflow


def test_ci_validates_openapi_schema():
    workflow = read_ci_workflow()

    assert "python manage.py spectacular" in workflow
    assert "--validate" in workflow
