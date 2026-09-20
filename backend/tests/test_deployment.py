from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import httpx
import pytest
import yaml
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.config import Settings
from backend.app.inference import BusinessCardLead
from backend.app.main import create_app

ROOT = Path(__file__).resolve().parents[2]


class NoopInference:
    async def extract(self, _image: bytes, _media_type: str) -> BusinessCardLead:
        return BusinessCardLead()


@pytest.mark.asyncio
async def test_fastapi_serves_vite_index_assets_and_spa_fallback(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (tmp_path / "index.html").write_text(
        '<main id="root">O-HIVE</main><script src="/assets/app.js"></script>',
        encoding="utf-8",
    )
    (assets / "app.js").write_text("console.log('app')", encoding="utf-8")
    app = create_app(
        settings=Settings(environment="test", frontend_dist=tmp_path),
        session_factory=session_factory,
        inference_client=NoopInference(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        root = await client.get("/")
        spa = await client.get("/batches/example")
        asset = await client.get("/assets/app.js")
        api_missing = await client.get("/api/not-a-route")

    assert root.status_code == 200 and "O-HIVE" in root.text
    assert spa.status_code == 200 and "O-HIVE" in spa.text
    assert asset.status_code == 200 and "console.log" in asset.text
    assert api_missing.status_code == 404


def test_root_dockerfile_builds_frontend_then_runs_single_fastapi_service() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.count("FROM ") >= 2
    assert "npm ci" in dockerfile
    assert "npm run build" in dockerfile
    assert "python:3.12" in dockerfile
    assert "frontend/dist" in dockerfile
    assert "alembic upgrade head" in dockerfile
    assert "uvicorn backend.app.main:app" in dockerfile
    assert "USER app" in dockerfile


def test_inference_image_uses_current_digest_pinned_runtime() -> None:
    dockerfile = (ROOT / "inference/Dockerfile").read_text(encoding="utf-8")
    requirements = (ROOT / "inference/requirements.txt").read_text(encoding="utf-8")

    assert "pytorch/pytorch:2.14.0-cuda12.6-cudnn9-runtime@sha256:" in dockerfile
    assert "PIP_BREAK_SYSTEM_PACKAGES=1" in dockerfile
    assert "torch==2.6.0" not in dockerfile
    assert "transformers>=5.10,<6" in requirements


def test_render_blueprint_has_exactly_one_web_service_and_external_postgres() -> None:
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))

    assert len(blueprint["services"]) == 1
    assert blueprint["services"][0]["type"] == "web"
    assert blueprint["services"][0]["runtime"] == "docker"
    assert blueprint["services"][0]["healthCheckPath"] == "/health"
    assert "databases" not in blueprint
    database_url = next(
        item
        for item in blueprint["services"][0]["envVars"]
        if item["key"] == "DATABASE_URL"
    )
    assert database_url == {"key": "DATABASE_URL", "sync": False}


def test_aws_template_uses_measured_cpu_host_private_origin_and_bounded_proxy() -> None:
    template = (ROOT / "infra/aws/inference-ec2.yaml").read_text(encoding="utf-8")

    assert "AWSAgentToolkit: aws-cloudformation@2" in template
    assert "m7i.xlarge" in template
    assert "HttpTokens: required" in template
    assert "Encrypted: true" in template
    assert "VolumeSize: 40" in template
    assert "MODEL_DEVICE=cpu" in template
    assert "MODEL_DTYPE=bfloat16" in template
    assert "TORCH_NUM_THREADS=4" in template
    assert "AWS::Lambda::Function" in template
    assert "AWS::Lambda::Url" in template
    assert "ReservedConcurrentExecutions: 2" in template
    assert "Action: lambda:InvokeFunctionUrl" in template
    assert "Action: lambda:InvokeFunction" in template
    assert "SourceSecurityGroupId" in template
    assert "AWS::EC2::VPCEndpoint" in template
    assert "Action: ssm:GetParameter" in template
    assert "resolve:ssm-secure" not in template
    assert "CidrIp: 0.0.0.0/0\n      Description: Authenticated" not in template
    assert "cloudflared" not in template.lower()
    for expensive_resource in (
        "AWS::EC2::NatGateway",
        "AWS::EC2::EIP",
        "AWS::ElasticLoadBalancingV2::LoadBalancer",
    ):
        assert expensive_resource not in template


def test_inline_lambda_proxy_is_valid_python() -> None:
    template = (ROOT / "infra/aws/inference-ec2.yaml").read_text(encoding="utf-8")
    inline = template.split("      Code:\n        ZipFile: |\n", 1)[1].split(
        "\n\n  InferenceProxyUrl:", 1
    )[0]

    ast.parse(textwrap.dedent(inline), filename="inference-proxy-inline.py")


def test_budget_template_contains_actual_and_forecast_alerts() -> None:
    template = (ROOT / "infra/aws/budget.yaml").read_text(encoding="utf-8")

    assert "AWS::Budgets::Budget" in template
    assert "NotificationType: ACTUAL" in template
    assert "NotificationType: FORECASTED" in template
    assert "AWSAgentToolkit: aws-cloudformation@2" in template


def test_environment_example_contains_placeholders_not_credential_values() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "DATABASE_URL=" in example
    assert "AWS_INFERENCE_ENDPOINT=https://" in example
    assert "AWS_INFERENCE_SHARED_SECRET=replace-" in example
    assert "AKIA" not in example
    assert "postgresql+asyncpg://user:password@" not in example
