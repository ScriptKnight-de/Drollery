"""The CI workflow that tests the project and publishes the Docker image. There is no YAML library in the project, so
these checks read the file as text; the point is to notice when someone breaks what the pipeline relies on."""
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).parent.parent
WORKFLOW = ROOT / ".forgejo/workflows/build.yml"


def workflow() -> str:
    return WORKFLOW.read_text()


def job_text(name: str) -> str:
    """The text of one job (from its `  name:` line to the next job)."""
    text = workflow()
    start = re.search(r"^  %s:\n" % re.escape(name), text, re.M)
    assert start, f"job {name} is missing"
    rest = text[start.end():]
    end = re.search(r"^  [a-z][\w-]*:\n", rest, re.M)
    return rest[: end.start()] if end else rest


def test_the_workflow_exists_where_the_other_projects_keep_theirs():
    assert WORKFLOW.is_file() and re.search(r"^name: build-image$", workflow(), re.M)


def test_it_runs_on_main_on_version_tags_weekly_and_on_demand():
    text = workflow()
    assert re.search(r"^on:\n  push:\n    branches: \[main\]\n    tags: \[\"v\*\"\]", text, re.M)
    assert re.search(r'- cron: "0 3 \* \* 1"', text) and "workflow_dispatch:" in text and "rebuild:" in text


def test_the_jobs_run_in_order_test_then_image_then_release():
    text = workflow()
    assert re.search(r"^jobs:\n  test:\n", text, re.M)
    assert "needs: test" in job_text("image") and "needs: image" in job_text("release")
    assert "startsWith(github.ref, 'refs/tags/v')" in job_text("release")                 # a release only on a version tag
    assert "needs:" not in job_text("test")
    for name in ("test", "image", "release"):
        assert "runs-on: docker" in job_text(name)


def test_the_tests_really_run_with_ffmpeg_and_a_skipped_test_fails_the_job():
    job = job_text("test")
    assert "ffmpeg" in job and "ffprobe" in job and "apt-get install" in job
    assert "shell: bash" in job and "set -o pipefail" in job
    assert 'pytest -q -rs' in job and "[0-9]+ skipped" in job and "exit 1" in job
    assert 'pip install -q -e ".[dev]"' in job
    # the reason this matters: the suite skips what needs ffmpeg when it is missing
    assert "ffmpeg/ffprobe required" in (ROOT / "tests/conftest.py").read_text()


def test_the_image_is_built_for_amd64_and_arm64_and_published_to_both_registries():
    text, job = workflow(), job_text("image")
    assert "platforms: linux/amd64,linux/arm64" in job and "push: true" in job
    assert "IMAGE: forgejo.scriptknight.de/scriptknight/drollery" in text
    assert "GHCR_IMAGE: ghcr.io/scriptknight-de/drollery" in text and "GH_REPO: ScriptKnight-de/drollery" in text
    assert "registry: ${{ env.REGISTRY }}" in job and "registry: ghcr.io" in job
    assert "DOCKER_HOST: tcp://dind:2375" in job                                            # the runner reaches docker through dind
    for tag in ("type=raw,value=latest,enable={{is_default_branch}}", "type=sha,format=short", "type=semver,pattern={{version}}", "type=semver,pattern={{major}}.{{minor}}"):
        assert tag in job, tag
    assert "docker buildx imagetools inspect" in job                                        # it checks that the push really arrived


def test_the_weekly_rebuild_uses_the_newest_release_without_cache_and_scans_it():
    job = job_text("image")
    assert "git tag --list 'v[0-9]*' --sort=-v:refname" in job and "no-cache: ${{ env.REBUILD == 'true' }}" in job
    assert "aquasec/trivy" in job and "--severity HIGH,CRITICAL --ignore-unfixed --exit-code 10" in job
    assert "github.event_name == 'schedule' || github.event.inputs.rebuild == 'true'" in job


def test_only_the_four_documented_secrets_are_used_and_never_written_out():
    text = workflow()
    used = set(re.findall(r"secrets\.([A-Z_]+)", text))
    assert used == {"REGISTRY_USER", "REGISTRY_TOKEN", "GH_USER", "GH_TOKEN"}
    header = text.split("name: build-image")[0]
    for name in used:
        assert name in header, f"{name} is not documented at the top of the workflow"
    assert not re.search(r"echo[^\n]*\$\{\{\s*secrets\.", text) and "set -x" not in text   # a secret is never echoed or traced


def test_the_release_notes_come_from_the_changelog_section_of_the_tag(tmp_path):
    import json
    body = workflow().split("python3 - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
    version = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    changelog = (ROOT / "CHANGELOG.md").read_text()
    (tmp_path / "CHANGELOG.md").write_text(changelog)

    def notes_for(tag):
        r = subprocess.run([sys.executable, "-c", textwrap.dedent(body)], cwd=tmp_path, env={**os.environ, "TAG": tag}, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return json.loads((tmp_path / "release.json").read_text())

    current = notes_for(f"v{version}")
    assert current["tag_name"] == f"v{version}" and current["name"] == f"Drollery {version}"
    expected = re.search(r"^## \[%s\][^\n]*\n(.*?)(?=^## \[|\Z)" % re.escape(version), changelog, re.M | re.S).group(1).strip()
    assert current["body"].startswith(expected) and expected                              # exactly this version's section ...
    assert f"docker pull ghcr.io/scriptknight-de/drollery:{version}" in current["body"]
    assert "## [" not in current["body"]                                                  # ... and nothing of the other versions
    first = notes_for("v0.1.0")                                                           # an older release still gets its own notes
    assert "First public release" in first["body"] and "docker pull ghcr.io/scriptknight-de/drollery:0.1.0" in first["body"]
    assert "## [" not in first["body"] and "ready-made image by default" not in first["body"]
    assert "See CHANGELOG.md." in notes_for("v99.0.0")["body"]                            # an unknown version still releases


def test_the_github_release_is_skipped_quietly_when_that_repository_does_not_exist():
    job = job_text("release")
    assert '!= 200' in job and "skipping the GitHub release" in job and "exit 0" in job
    assert "already exists, skipping" in job                                                  # and re-running a tag does not fail


def test_the_dockerfile_carries_the_labels_of_the_other_projects_and_stays_safe():
    docker = (ROOT / "Dockerfile").read_text()
    for label in ("org.opencontainers.image.title", "org.opencontainers.image.source=\"https://github.com/ScriptKnight-de/drollery\"",
                  "org.opencontainers.image.licenses=\"MIT\"", "de.scriptknight.donate=\"https://ko-fi.com/scriptknight\""):
        assert label in docker, label
    assert re.search(r"^FROM python:3\.\d+-slim$", docker, re.M)                              # a multi-architecture base image
    assert "USER drollery" in docker and "HEALTHCHECK" in docker and "ffmpeg" in docker
    ignored = (ROOT / ".dockerignore").read_text().split()
    for must in (".git", ".env", "data", "tests"):
        assert must in ignored, f"{must} must stay out of the image"


def test_the_readme_tells_people_to_pull_the_image_the_workflow_publishes():
    readme = (ROOT / "README.md").read_text()
    ghcr = re.search(r"^  GHCR_IMAGE: (\S+)$", workflow(), re.M).group(1)
    version = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    assert "docker run -d --name drollery" in readme and f"{ghcr}:latest" in readme and f"{ghcr}:{version}" in readme   # the example names the current release
    assert f"`{version[:version.rfind('.')]}`" in readme and "forgejo.scriptknight.de/scriptknight/drollery" in readme    # and the tags are explained
    docker = (ROOT / "Dockerfile").read_text()
    port = re.search(r"^EXPOSE (\d+)", docker, re.M).group(1)
    volume = re.search(r"^VOLUME (\S+)", docker, re.M).group(1)
    assert f"-p {port}:{port}" in readme and f"-v drollery-data:{volume}" in readme and f'"{port}:{port}"' in readme     # the commands match the image
    assert "linux/amd64" in workflow() and "amd64" in readme and "arm64" in readme


def test_the_changelog_mentions_the_published_image():
    assert "ghcr.io/scriptknight-de/drollery" in (ROOT / "CHANGELOG.md").read_text()


def test_the_compose_file_pulls_the_published_image_and_can_still_build_it():
    compose = (ROOT / "docker-compose.yml").read_text()
    ghcr = re.search(r"^  GHCR_IMAGE: (\S+)$", workflow(), re.M).group(1)
    drollery = compose.split("  drollery:\n", 1)[1].split("\n  # ----", 1)[0]
    assert f"image: ${{DROLLERY_IMAGE:-{ghcr}:latest}}" in drollery                       # the image the workflow publishes, overridable
    assert "build:\n      context: ." in drollery                                        # and `--build` still builds from source
    assert "pull_policy" not in drollery                                                  # the default does what the README says
    env = (ROOT / ".env.example").read_text()
    assert re.search(r"^DROLLERY_IMAGE=$", env, re.M) and "DROLLERY_IMAGE" in (ROOT / "docs/configuration.md").read_text()
    readme = (ROOT / "README.md").read_text()
    assert "docker compose up -d               # add --build" in readme and "docker compose pull && docker compose up -d" in readme
