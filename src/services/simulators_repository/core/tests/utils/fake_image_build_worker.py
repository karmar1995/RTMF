from services.simulators_repository.core.abstract_image_build_worker import (
    AbstractImageBuildWorker,
    BuildRequest,
    BuildResult,
    BuildStatus,
)


class FakeImageBuildWorker(AbstractImageBuildWorker):
    def __init__(
        self,
        polls_to_complete: int = 1,
        final_status: BuildStatus = BuildStatus.SUCCEEDED,
    ) -> None:
        if polls_to_complete < 0:
            raise ValueError("polls_to_complete must be >= 0")
        self._results = {}
        self._poll_counts = {}
        self._default_polls_to_complete = polls_to_complete
        self._default_final_status = final_status
        self._polls_to_complete = {}
        self._final_status = {}

    def submit_build(self, request: BuildRequest) -> str:
        self._results[request.build_id] = BuildResult(
            build_id=request.build_id,
            status=BuildStatus.RUNNING,
            image_ref="fake.registry/simulators/test:latest",
            image_digest="sha256:fake",
            image_tags=["latest"],
            logs="",
            error="",
        )
        self._poll_counts[request.build_id] = 0
        self._polls_to_complete[request.build_id] = self._default_polls_to_complete
        self._final_status[request.build_id] = self._default_final_status
        return request.build_id

    def get_build_status(self, build_id: str) -> BuildResult:
        result = self._results.get(build_id)
        if result is None:
            raise RuntimeError(f"Unknown build id: {build_id}")
        if result.status == BuildStatus.RUNNING:
            self._poll_counts[build_id] += 1
            if self._poll_counts[build_id] >= self._polls_to_complete[build_id]:
                self._results[build_id] = BuildResult(
                    build_id=build_id,
                    status=self._final_status[build_id],
                    image_ref=result.image_ref,
                    image_digest=result.image_digest,
                    image_tags=result.image_tags,
                    logs=result.logs,
                    error=result.error,
                )
                result = self._results[build_id]
        return result

    def cancel_build(self, build_id: str) -> bool:
        return False

    def configure_build(
        self,
        build_id: str,
        final_status: BuildStatus = BuildStatus.SUCCEEDED,
        polls_to_complete: int = 1,
    ) -> None:
        if polls_to_complete < 0:
            raise ValueError("polls_to_complete must be >= 0")
        if build_id not in self._results:
            raise RuntimeError(f"Unknown build id: {build_id}")
        self._final_status[build_id] = final_status
        self._polls_to_complete[build_id] = polls_to_complete
