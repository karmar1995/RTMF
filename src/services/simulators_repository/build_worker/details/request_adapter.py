import copy


def parseRequest(request):
    """
    Convert BuildRequest into DockerfileDirector configuration dict.

    Assumptions:
    - request.build_spec is ALREADY in the exact config format expected by
      DockerfileDirector.render().
    - request.zip_bytes is already saved in the Docker build context as "upload.zip".
    - artifacts.zip.path is defaulted to "upload.zip" when missing.
    """
    if request is None:
        raise ValueError("request is required")

    if not isinstance(request.build_spec, dict):
        raise ValueError("request.build_spec must be a dict")

    if not isinstance(request.zip_filename, str) or not request.zip_filename.strip():
        raise ValueError("request.zip_filename must be a non-empty string")

    if not isinstance(request.zip_bytes, (bytes, bytearray)) or not request.zip_bytes:
        raise ValueError("request.zip_bytes must be non-empty bytes")

    config = copy.deepcopy(request.build_spec)

    artifacts = config.get("artifacts")
    if artifacts is None:
        config["artifacts"] = {"zip": {"path": "upload.zip"}}
    elif isinstance(artifacts, dict):
        zip_cfg = artifacts.get("zip")
        if zip_cfg is None:
            artifacts["zip"] = {"path": "upload.zip"}
        elif isinstance(zip_cfg, dict) and "path" not in zip_cfg:
            zip_cfg["path"] = "upload.zip"

    return config
