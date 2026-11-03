import json
from pathlib import Path
from urllib.parse import urlsplit


def test_local_services_share_database_required_by_simulator_foreign_keys() -> None:
    template = Path(__file__).resolve().parents[2] / "config/rtmf.local.example.json"
    services = json.loads(template.read_text(encoding="utf-8"))["services"]
    dsns = [
        repository["dsn"]
        for service in services.values()
        for repository in service.get("postgres", {}).values()
    ]
    dsns.append(services["jobs_scheduler"]["slurm"]["postgres_dsn"])

    # Registration, scheduling, evaluation, and workers share simulator IDs.
    # Their foreign keys and joins cannot cross PostgreSQL database boundaries.
    connections = [urlsplit(dsn) for dsn in dsns]
    database_targets = {
        (connection.hostname, connection.port or 5432, connection.path)
        for connection in connections
    }
    assert len(database_targets) == 1, database_targets
