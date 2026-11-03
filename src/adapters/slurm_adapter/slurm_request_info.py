from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlurmRequestInfo:
    docker_username: str
    docker_password: str
    minio_endpoint: str
    minio_user: str
    minio_password: str
    job_executor_user: str
    job_executor_group: str
    postgres_dsn: str

    def to_env_list(self) -> list[str]:
        return [
            f"APPTAINER_DOCKER_USERNAME={self.docker_username}",
            f"APPTAINER_DOCKER_PASSWORD={self.docker_password}",
            f"MINIO_ENDPOINT={self.minio_endpoint}",
            f"MINIO_USER={self.minio_user}",
            f"MINIO_PASSWORD={self.minio_password}",
            f"JOB_EXECUTOR_USER={self.job_executor_user}",
            f"JOB_EXECUTOR_GROUP={self.job_executor_group}",
            f"POSTGRES_DSN={self.postgres_dsn}"
        ]
