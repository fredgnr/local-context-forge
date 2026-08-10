from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTAINER_WORKFLOW = (
    PROJECT_ROOT / ".github" / "workflows" / "container-images.yml"
)
WEB_DOCKERFILE = PROJECT_ROOT / "web" / "Dockerfile"
WEB_DOCKERIGNORE = PROJECT_ROOT / "web" / ".dockerignore"


def _workflow() -> str:
    return CONTAINER_WORKFLOW.read_text(encoding="utf-8")


def _dockerfile_stages() -> tuple[str, str]:
    dockerfile = WEB_DOCKERFILE.read_text(encoding="utf-8")
    stage_headers = list(re.finditer(r"^FROM .+$", dockerfile, re.M))
    assert len(stage_headers) == 2
    build_start = stage_headers[0].start()
    runtime_start = stage_headers[1].start()
    return dockerfile[build_start:runtime_start], dockerfile[runtime_start:]


def _workflow_step(workflow: str, name: str) -> str:
    match = re.search(
        rf"^      - name: {re.escape(name)}\n.*?(?=^      - name: |\Z)",
        workflow,
        re.M | re.S,
    )
    assert match is not None
    return match.group(0).rstrip()


def test_web_build_runs_node_on_build_platform_only() -> None:
    build, runtime = _dockerfile_stages()

    assert build.startswith(
        "FROM --platform=$BUILDPLATFORM node:22-alpine AS build\n"
    )
    assert "RUN npm ci\n" in build
    assert "RUN npm run build\n" in build
    assert "nginx" not in build

    assert runtime.startswith("FROM nginx:1.27-alpine\n")
    assert "--platform=" not in runtime
    assert "npm" not in runtime
    assert "COPY --from=build /app/dist /usr/share/nginx/html" in runtime
    assert runtime.count("COPY --from=build") == 1
    assert "node_modules" not in runtime

    ignored = set(WEB_DOCKERIGNORE.read_text(encoding="utf-8").splitlines())
    assert {"node_modules", "dist", ".vite"}.issubset(ignored)


def test_container_workflow_keeps_dual_target_platforms_and_publish_policy() -> None:
    workflow = _workflow()

    trigger, separator, _remainder = workflow.partition("\nconcurrency:\n")
    assert separator
    assert trigger == (
        "name: Build and publish container images\n\n"
        "on:\n"
        "  push:\n"
        "    branches:\n"
        "      - main\n"
        "    tags:\n"
        '      - "v*.*.*"\n'
        "  pull_request:\n"
        "    branches:\n"
        "      - main\n"
        "  workflow_dispatch:\n"
    )
    assert "pull_request_target:" not in workflow
    assert "schedule:" not in workflow
    assert "permissions:\n  contents: read\n" in workflow
    assert (
        "    permissions:\n"
        "      contents: read\n"
        "      packages: write\n"
    ) in workflow

    matrix = workflow.partition("      matrix:\n")[2].partition("\n\n    env:\n")[0]
    assert matrix == (
        "        include:\n"
        "          - service: api\n"
        "            context: ./backend\n"
        "            dockerfile: ./docker/api.Dockerfile\n"
        "            build_args: |\n"
        "              QMD_VERSION=2.5.3\n"
        "          - service: mcp\n"
        "            context: ./mcp\n"
        "            dockerfile: ./docker/mcp.Dockerfile\n"
        '            build_args: ""\n'
        "          - service: web\n"
        "            context: ./web\n"
        "            dockerfile: ./web/Dockerfile\n"
        "            build_args: |\n"
        "              VITE_API_BASE=/api"
    )
    assert workflow.count("platforms: linux/amd64,linux/arm64") == 1
    assert "timeout-minutes: 120" in workflow

    qemu = _workflow_step(workflow, "Set up QEMU")
    assert (
        "docker/setup-qemu-action@"
        "ce360397dd3f832beb865e1373c09c0e9f86d70a"
    ) in qemu
    assert "          platforms: arm64" in qemu
    buildx = _workflow_step(workflow, "Set up Docker Buildx")
    assert (
        "docker/setup-buildx-action@"
        "d7f5e7f509e45cec5c76c4d5afdd7de93d0b3df5"
    ) in buildx

    login = _workflow_step(workflow, "Log in to GHCR")
    assert "if: github.event_name != 'pull_request'" in login
    assert (
        "docker/login-action@4907a6ddec9925e35a0a9e82d7399ccc52663121"
        in login
    )
    assert "registry: ${{ env.REGISTRY }}" in login
    assert "username: ${{ github.actor }}" in login
    assert "password: ${{ secrets.GITHUB_TOKEN }}" in login

    metadata = _workflow_step(workflow, "Generate image metadata")
    for tag in (
        "type=raw,value=main,enable={{is_default_branch}}",
        "type=sha,prefix=sha-",
        "type=semver,pattern={{version}}",
        "type=semver,pattern={{major}}.{{minor}}",
    ):
        assert tag in metadata

    build = _workflow_step(workflow, "Build and publish")
    assert (
        "docker/build-push-action@"
        "f9f3042f7e2789586610d6e8b85c8f03e5195baf"
    ) in build
    assert "platforms: linux/amd64,linux/arm64" in build
    assert "push: ${{ github.event_name != 'pull_request' }}" in build
    assert "load:" not in build

    published = _workflow_step(workflow, "Verify published platforms")
    assert "if: github.event_name != 'pull_request'" in published
    assert "grep -q 'linux/amd64'" in published
    assert "grep -q 'linux/arm64'" in published

    assert workflow.count("if: github.event_name != 'pull_request'") == 2
    assert workflow.count("docker/login-action@") == 1
    assert "load:" not in workflow
    assert "actions/upload-artifact" not in workflow
    assert "docker load" not in workflow


def test_container_workflow_builds_exact_pr_head_without_credentials() -> None:
    workflow = _workflow()
    checkout_expression = (
        "${{ github.event.pull_request.head.sha || github.sha }}"
    )

    assert f"ref: {checkout_expression}" in workflow
    assert "persist-credentials: false" in workflow
    assert "name: Verify exact source checkout" in workflow
    assert f"LCF_SOURCE_SHA: {checkout_expression}" in workflow
    assert 'test "$(git rev-parse HEAD)" = "$LCF_SOURCE_SHA"' in workflow
