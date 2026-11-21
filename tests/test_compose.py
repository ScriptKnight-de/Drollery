"""The Docker Compose file. The Whisper model helper is a small shell script inside it; it is run here for real, with a stand-in
for curl, so what a person sees when the model download fails (and that it fails at all) is pinned down."""
import os
import re
import subprocess
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
COMPOSE = (ROOT / "docker-compose.yml").read_text()


def helper_section() -> str:
    return COMPOSE.split("  whisper-model:\n", 1)[1].split("\nvolumes:", 1)[0]


def helper_script(model: str = "Systran/faster-whisper-small") -> str:
    """The script exactly as the container's shell receives it: Compose first fills in ${WHISPER_MODEL:-…} and turns $$ into $."""
    block = helper_section().split("      - |\n", 1)[1]
    lines = [ln[8:] if ln.startswith("        ") else ln for ln in block.splitlines()]
    text = "\n".join(lines)
    assert "${WHISPER_MODEL:-Systran/faster-whisper-small}" in text
    return text.replace("${WHISPER_MODEL:-Systran/faster-whisper-small}", model).replace("$$", "$")


@pytest.fixture()
def run_helper(tmp_path):
    """Run the helper with a fake curl that answers with a scripted sequence of (http code, body, curl exit code)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "curl").write_text('''#!/bin/sh
n=$(cat "$STUB_DIR/calls" 2>/dev/null || echo 0); n=$((n + 1)); echo $n > "$STUB_DIR/calls"
line=$(sed -n "${n}p" "$STUB_DIR/script" 2>/dev/null); [ -n "$line" ] || line=$(tail -n 1 "$STUB_DIR/script")
code=${line%%|*}; rest=${line#*|}; body=${rest%%|*}; exit_code=${rest#*|}
out=""; while [ $# -gt 0 ]; do [ "$1" = "-o" ] && out="$2"; shift; done
[ -n "$out" ] && printf '%s' "$body" > "$out"
if [ "$exit_code" != 0 ]; then echo "curl: ($exit_code) $body" >&2; exit "$exit_code"; fi
printf '%s' "$code"
''')
    (bin_dir / "sleep").write_text("#!/bin/sh\nexit 0\n")
    for tool in ("curl", "sleep"):
        (bin_dir / tool).chmod((bin_dir / tool).stat().st_mode | stat.S_IEXEC)

    def run(*answers, model="Systran/faster-whisper-small"):
        for leftover in ("/tmp/answer", "/tmp/curl-error"):
            Path(leftover).unlink(missing_ok=True)
        (tmp_path / "script").write_text("\n".join("|".join(a) for a in answers) + "\n")
        (tmp_path / "calls").write_text("0")
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "STUB_DIR": str(tmp_path)}
        r = subprocess.run(["sh", "-c", helper_script(model)], env=env, capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout + r.stderr, int((tmp_path / "calls").read_text())

    return run


def test_a_successful_download_prints_the_servers_answer_and_exits_cleanly(run_helper):
    code, out, calls = run_helper(("200", "Model 'Systran/faster-whisper-small' downloaded", "0"))
    assert code == 0 and calls == 1
    assert "Downloading the Whisper model Systran/faster-whisper-small" in out and "Model 'Systran/faster-whisper-small' downloaded" in out
    assert "ERROR" not in out


def test_a_wrong_model_name_is_named_and_not_retried(run_helper):
    code, out, calls = run_helper(("404", '{"detail":"Model \'Systran/nope\' not found"}', "0"), model="Systran/nope")
    assert code == 1 and calls == 1                                                          # a 404 will not get better by waiting
    assert "ERROR: could not download the Whisper model 'Systran/nope' (HTTP 404)" in out
    assert "The Whisper server answered: " in out and "not found" in out                    # the server's own words
    assert "Check WHISPER_MODEL in .env" in out


def test_a_server_error_is_retried_then_explained_with_the_usual_cause_and_where_to_look(run_helper):
    code, out, calls = run_helper(("500", "Internal Server Error", "0"))
    assert code == 1 and calls == 3
    assert "Attempt 1 failed (HTTP 500)" in out and "Attempt 2 failed (HTTP 500)" in out and "Attempt 3 failed" not in out
    assert "ERROR: could not download the Whisper model 'Systran/faster-whisper-small' (HTTP 500)" in out
    assert "The Whisper server answered: Internal Server Error" in out
    assert "huggingface.co" in out and "docker compose logs whisper" in out and "DNS, firewall or proxy" in out


def test_a_passing_problem_is_survived(run_helper):
    code, out, calls = run_helper(("503", "busy", "0"), ("500", "again", "0"), ("200", "Model downloaded", "0"))
    assert code == 0 and calls == 3 and "Attempt 2 failed (HTTP 500)" in out and "Model downloaded" in out and "ERROR" not in out


def test_an_unreachable_server_shows_curls_own_message_and_how_to_check_the_container(run_helper):
    code, out, calls = run_helper(("000", "Could not resolve host: whisper", "6"))
    assert code == 1 and calls == 3
    assert "(HTTP 000)" in out and "Could not reach the Whisper server at http://whisper:8000" in out
    assert "Could not resolve host: whisper" in out and "docker compose ps" in out


@pytest.mark.parametrize("status", ["401", "403", "409", "422"])
def test_any_other_answer_is_shown_and_fails_once(run_helper, status):
    code, out, calls = run_helper((status, f"answer {status}", "0"))
    assert code == 1 and calls == 1 and f"(HTTP {status})" in out and f"answer {status}" in out and "docker compose logs whisper" in out


def test_a_long_answer_is_cut_short(run_helper):
    code, out, _ = run_helper(("400", "x" * 5000, "0"))
    assert code == 1 and "x" * 500 in out and "x" * 501 not in out


def test_the_helper_no_longer_hides_the_answer_behind_curls_fail_flag():
    script = helper_script()
    assert "curl -fsS" not in script and "-w '%{http_code}'" in script and "--max-time 3600" in script
    assert "exit 1" in script and "exit 0" in script


def test_dollar_signs_are_escaped_for_compose_except_the_model_default():
    section = helper_section().split("      - |\n", 1)[1]
    stray = [m.group(0) for m in re.finditer(r"(?<!\$)\$(?!\$)[^\n]{0,30}", section) if not m.group(0).startswith("${WHISPER_MODEL:-")]
    assert not stray, f"Compose would try to fill these in itself: {stray[:3]}"


def test_the_helper_is_still_a_one_shot_that_waits_for_a_healthy_server_and_only_runs_on_request():
    section = helper_section()
    assert 'profiles: ["whisper"]' in section and 'restart: "no"' in section
    assert "service_healthy" in section and "image: ghcr.io/speaches-ai/speaches" in section
    assert re.search(r"^  whisper:\n(?:.*\n)*?    healthcheck:", COMPOSE, re.M)
