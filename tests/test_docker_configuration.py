from pathlib import Path


def test_dockerfile_uses_python_312_slim_and_non_root_user() -> None:
    content = Path("Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.12-slim" in content
    assert "USER app" in content
    assert "WORKDIR /app" in content


def test_dockerfile_does_not_run_migrations_or_reload() -> None:
    content = Path("Dockerfile").read_text(encoding="utf-8")

    assert "alembic upgrade" not in content
    assert "--reload" not in content
    assert ".env" not in content
    assert ".git" not in content


def test_dockerignore_excludes_secrets_and_git() -> None:
    content = Path(".dockerignore").read_text(encoding="utf-8")

    assert ".env" in content
    assert ".git" in content
    assert "tests" in content


def test_compose_has_required_services_and_separate_commands() -> None:
    content = Path("compose.production.yml").read_text(encoding="utf-8")

    for service in ("postgres:", "migrate:", "api:", "inbound-worker:", "outbound-worker:"):
        assert service in content
    assert '["alembic", "upgrade", "head"]' in content
    assert '["python", "-m", "app.workers.inbound_message_worker"]' in content
    assert '["python", "-m", "app.workers.outbound_message_worker"]' in content
    assert "--reload" not in content


def test_compose_security_basics() -> None:
    content = Path("compose.production.yml").read_text(encoding="utf-8")

    assert "privileged: true" not in content
    assert "/var/run/docker.sock" not in content
    assert "postgres_data:" in content
    assert "service_completed_successfully" in content
    assert "service_healthy" in content
    assert "${POSTGRES_PASSWORD}" in content
    assert "CHANGE_ME" not in content
