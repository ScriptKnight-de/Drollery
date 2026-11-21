"""Links to private or local addresses are not fetched by default. The network is replaced by fakes: nothing here goes online."""
import json

import httpx
import pytest

from drollery import db, netguard, pipeline, providers
from drollery.config import get_settings
from test_app import png

PUBLIC = "93.184.216.34"


@pytest.fixture()
def dns(monkeypatch):
    """Names resolve to what the test says; anything else is looked up for real (IP literals, localhost)."""
    table = {}
    real = netguard._resolve

    def fake(host):
        return table[host] if host in table else real(host)

    monkeypatch.setattr(netguard, "_resolve", fake)
    return table


def blocked(url):
    with pytest.raises(netguard.BlockedAddress):
        netguard.check_url(url)


# ------------------------------------------------------------ which addresses are public

@pytest.mark.parametrize("address", [
    "10.0.0.1", "10.255.255.255", "172.16.0.1", "172.31.255.254", "192.168.0.1", "192.168.50.7", "127.0.0.1", "127.1.2.3", "0.0.0.0",
    "169.254.169.254", "169.254.0.1", "100.64.0.1", "224.0.0.1", "255.255.255.255", "192.0.2.1", "198.18.0.1",
    "::1", "::", "fe80::1", "fc00::1", "fd12:3456::1", "ff02::1", "::ffff:127.0.0.1", "::ffff:10.1.2.3", "64:ff9b::7f00:1", "64:ff9b::a00:1", "2002:7f00:1::1", "2002:a00:1::",
])
def test_private_local_and_reserved_addresses_are_not_public(address):
    assert netguard.is_public(address) is False


@pytest.mark.parametrize("address", [PUBLIC, "8.8.8.8", "1.1.1.1", "172.32.0.1", "172.15.255.255", "2606:2800:220:1:248:1893:25c8:1946", "::ffff:8.8.8.8", "64:ff9b::808:808"])
def test_public_addresses_are_public(address):
    assert netguard.is_public(address) is True


def test_a_value_that_is_not_an_address_is_not_public():
    assert netguard.is_public("not-an-ip") is False and netguard.is_public("") is False


# ------------------------------------------------------------ links

@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://127.0.0.1:8080/api", "http://localhost/", "http://LOCALHOST./x", "http://[::1]/", "http://[::ffff:7f00:1]/", "http://10.1.2.3/",
    "http://192.168.1.1/admin", "http://169.254.169.254/latest/meta-data/", "http://0.0.0.0/", "http://0/", "http://2130706433/", "http://0x7f.0.0.1/",
    "http://0177.0.0.1/", "http://127.1/", "https://user:pw@127.0.0.1/", "http://[fe80::1]/", "http://[fd00::1]/",
])
def test_the_usual_ways_of_writing_a_local_address_are_all_caught(url):
    blocked(url)


def test_a_name_that_resolves_to_a_private_address_is_caught(dns):
    dns["internal.example"] = ["192.168.1.50"]
    dns["rebind.example"] = [PUBLIC, "10.0.0.5"]                                       # one bad answer among good ones is enough
    dns["meta.example"] = ["169.254.169.254"]
    for url in ("http://internal.example/x", "http://rebind.example/", "http://meta.example/"):
        blocked(url)


def test_public_names_and_addresses_pass(dns):
    dns["cdn.example"] = [PUBLIC]
    for url in ("https://cdn.example/a.png", f"http://{PUBLIC}/a.png", "https://[2606:2800:220:1:248:1893:25c8:1946]/", "http://8.8.8.8:8080/x"):
        netguard.check_url(url)


def test_a_name_that_does_not_resolve_is_left_to_fail_by_itself(monkeypatch):
    import socket

    def no_such_host(*args, **kwargs):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", no_such_host)
    netguard.check_url("http://does-not-exist.invalid/x")                               # nothing was reached, so there is nothing to block


def test_a_link_without_a_host_is_refused():
    for url in ("http:///x", "https://", "http://:80/"):
        with pytest.raises(netguard.BlockedAddress) as e:
            netguard.check_url(url)
        assert "no address" in str(e.value)


def test_the_message_names_the_host_and_says_how_to_allow_it():
    with pytest.raises(netguard.BlockedAddress) as e:
        netguard.check_url("http://192.168.1.50/x")
    assert "192.168.1.50" in str(e.value) and "allow_private_fetch" in str(e.value) and "fetch_allow_hosts" in str(e.value)


# ------------------------------------------------------------ the owner's switches

def test_the_default_is_to_block(client):
    s = get_settings()
    assert s.allow_private_fetch is False and s.fetch_allow_hosts == []
    blocked("http://192.168.1.50/x")


def test_the_whole_check_can_be_switched_off(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_private_fetch", True)
    netguard.check_url("http://127.0.0.1/x")
    netguard.check_redirects("http://127.0.0.1/x")                                       # (no request is made when it is switched off)


def test_chosen_hosts_networks_and_addresses_can_be_allowed_and_nothing_else(client, monkeypatch, dns):
    dns["nas.lan"] = ["192.168.1.20"]
    dns["other.lan"] = ["192.168.1.21"]
    monkeypatch.setattr(get_settings(), "fetch_allow_hosts", ["nas.lan", "10.0.0.0/24", "172.16.5.9", "  NAS2.lan. "])
    for url in ("http://nas.lan/a", "http://10.0.0.77/a", "http://10.0.0.1:8080/", "http://172.16.5.9/", "http://nas2.lan/"):
        netguard.check_url(url)
    for url in ("http://other.lan/a", "http://10.0.1.1/", "http://172.16.5.10/", "http://127.0.0.1/", "http://192.168.1.21/"):
        blocked(url)


def test_a_name_on_the_allow_list_stays_allowed_whatever_it_resolves_to(client, monkeypatch, dns):
    dns["nas.lan"] = ["127.0.0.1"]
    monkeypatch.setattr(get_settings(), "fetch_allow_hosts", ["nas.lan"])
    netguard.check_url("http://nas.lan/")                                                # the owner named it, so it is theirs to vouch for


def test_a_network_on_the_allow_list_covers_the_names_that_resolve_into_it(client, monkeypatch, dns):
    dns["a.lan"] = ["10.0.0.5"]
    dns["b.lan"] = ["10.0.9.5"]
    monkeypatch.setattr(get_settings(), "fetch_allow_hosts", ["10.0.0.0/24"])
    netguard.check_url("http://a.lan/")
    blocked("http://b.lan/")


def test_the_defaults_are_written_in_the_config_file_that_users_copy():
    from importlib import resources
    text = resources.files("drollery").joinpath("config.default.toml").read_text()
    assert "allow_private_fetch = false" in text and "fetch_allow_hosts = []" in text


# ------------------------------------------------------------ adding a link

def lookups(monkeypatch):
    calls = []
    monkeypatch.setattr(netguard, "_resolve", lambda host: calls.append(host) or [PUBLIC])
    return calls


def test_the_api_refuses_a_private_link_and_queues_nothing(client):
    r = client.post("/api/v1/ingest", json={"url": "http://192.168.1.1/admin"})
    assert r.status_code == 422 and "private or local network address" in r.json()["detail"] and "192.168.1.1" in r.json()["detail"]
    for url in ("http://localhost:8080/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/"):
        assert client.post("/api/v1/ingest", json={"url": url}).status_code == 422
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_the_api_still_queues_a_public_link(client, monkeypatch):
    lookups(monkeypatch)
    r = client.post("/api/v1/ingest", json={"url": "https://media.example/funny.gif"})
    assert r.status_code == 202 and r.json()["job_id"]
    with db.tx() as c:
        assert json.loads(c.execute("SELECT payload FROM jobs").fetchone()["payload"]) == {"url": "https://media.example/funny.gif"}


def test_the_web_form_explains_a_refusal_in_the_page_language_and_queues_nothing(client):
    r = client.post("/add", data={"url": "http://192.168.1.1/admin"})
    assert r.status_code == 200 and "private or local network address" in r.text and "192.168.1.1" in r.text
    client.post("/language", data={"language": "de", "next": "/"})
    assert "private oder lokale Netzwerkadresse" in client.post("/add", data={"url": "http://127.0.0.1:8080/"}).text
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_the_web_form_still_accepts_a_public_link(client, monkeypatch):
    lookups(monkeypatch)
    r = client.post("/add", data={"url": "https://media.example/funny.gif"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/jobs"
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM jobs WHERE type='fetch'").fetchone()[0] == 1


def test_the_unified_upload_zone_shows_the_refusal(client):
    from drollery.web import FLASH
    r = client.post("/add", data={"url": "http://10.0.0.5/x"}, headers={"X-Drollery-Upload": "1"}, follow_redirects=False)
    assert r.status_code == 200 and r.json() == {"redirect": "/"}
    assert FLASH in "".join(r.headers.get_list("set-cookie"))                            # the message travels with the redirect
    assert "10.0.0.5" in client.get("/").text


# ------------------------------------------------------------ the download job

def run_job(url):
    job = {"id": 1, "type": "fetch", "item_id": None, "payload": json.dumps({"url": url}), "attempts": 1}
    pipeline.job_fetch(job)


def test_a_queued_job_for_a_private_link_fails_before_anything_is_requested(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the network was used")
    monkeypatch.setattr(netguard, "make_client", boom)
    monkeypatch.setattr(pipeline, "_run_tool", boom)
    with pytest.raises(netguard.BlockedAddress) as e:
        run_job("http://192.168.1.50/secret.png")
    assert "192.168.1.50" in str(e.value)


def client_for(handler):
    return lambda: httpx.Client(transport=httpx.MockTransport(handler), timeout=30)


def test_a_redirect_to_a_private_address_is_not_followed(client, monkeypatch, dns, tmp_path):
    dns["cdn.example"] = [PUBLIC]
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    monkeypatch.setattr(netguard, "make_client", client_for(handler))
    with pytest.raises(netguard.BlockedAddress):
        pipeline._direct_download("https://cdn.example/pic.png", tmp_path)
    assert seen == ["https://cdn.example/pic.png"]                                       # the second request never went out


def test_a_relative_redirect_and_a_chain_of_public_hops_still_work(client, monkeypatch, dns, tmp_path):
    dns["cdn.example"] = [PUBLIC]
    dns["files.example"] = [PUBLIC]
    picture = png(33)
    hops = []

    def handler(request):
        hops.append(str(request.url))
        if request.url.path == "/short":
            return httpx.Response(301, headers={"location": "/pic.png"})
        if request.url.host == "cdn.example":
            return httpx.Response(307, headers={"location": "https://files.example/final.png"})
        return httpx.Response(200, content=picture, headers={"content-type": "image/png"})

    monkeypatch.setattr(netguard, "make_client", client_for(handler))
    files = pipeline._direct_download("https://cdn.example/short", tmp_path)
    assert [f.name for f in files] == ["final.png"] and files[0].read_bytes() == picture
    assert hops == ["https://cdn.example/short", "https://cdn.example/pic.png", "https://files.example/final.png"]


def test_a_redirect_loop_gives_up(client, monkeypatch, dns, tmp_path):
    dns["loop.example"] = [PUBLIC]
    monkeypatch.setattr(netguard, "make_client", client_for(lambda r: httpx.Response(302, headers={"location": "https://loop.example/again"})))
    with pytest.raises(providers.ProviderError, match="too many redirects"):
        pipeline._direct_download("https://loop.example/start", tmp_path)


def test_the_downloaders_are_only_started_after_the_redirects_were_checked(client, monkeypatch, dns):
    dns["short.example"] = [PUBLIC]

    def handler(request):
        return httpx.Response(302, headers={"location": "http://10.0.0.7/internal"})

    started = []
    monkeypatch.setattr(netguard, "make_client", client_for(handler))
    monkeypatch.setattr(pipeline, "_direct_download", lambda url, td: [])
    monkeypatch.setattr(pipeline, "_run_tool", lambda cmd, timeout: started.append(cmd))
    with pytest.raises(netguard.BlockedAddress):
        run_job("https://short.example/watch")
    assert started == []                                                                  # neither yt-dlp nor gallery-dl was run


def test_a_clean_chain_lets_the_downloader_run(client, monkeypatch, dns):
    dns["video.example"] = [PUBLIC]
    dns["www.video.example"] = [PUBLIC]
    handler = lambda request: (httpx.Response(301, headers={"location": "https://www.video.example/watch"}) if request.url.host == "video.example" else httpx.Response(200))  # noqa: E731
    monkeypatch.setattr(netguard, "make_client", client_for(handler))
    monkeypatch.setattr(pipeline, "_direct_download", lambda url, td: [])
    started = []
    monkeypatch.setattr(pipeline, "_run_tool", lambda cmd, timeout: started.append(cmd[0]) or type("R", (), {"stderr": "", "returncode": 1})())
    with pytest.raises(providers.ProviderError, match="nothing downloadable"):
        run_job("https://video.example/start")
    assert started == ["yt-dlp", "gallery-dl"]


def test_a_server_that_refuses_head_does_not_stop_the_walk(client, monkeypatch, dns):
    dns["video.example"] = [PUBLIC]

    def handler(request):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(netguard, "make_client", client_for(handler))
    netguard.check_redirects("https://video.example/watch")                              # nothing to learn, so nothing is blocked


def test_the_redirect_walk_stops_at_the_first_private_hop(client, monkeypatch, dns):
    dns["a.example"] = [PUBLIC]
    n = []

    def handler(request):
        n.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://10.9.9.9/x" if len(n) >= 3 else "https://a.example/next"})

    monkeypatch.setattr(netguard, "make_client", client_for(handler))
    with pytest.raises(netguard.BlockedAddress):
        netguard.check_redirects("https://a.example/start")
    assert len(n) == 3                                                                    # nothing after the private hop was asked for


def test_a_very_long_chain_of_public_hops_is_walked_only_so_far(client, monkeypatch, dns):
    dns["a.example"] = [PUBLIC]
    n = []
    monkeypatch.setattr(netguard, "make_client", client_for(lambda r: n.append(1) or httpx.Response(302, headers={"location": "https://a.example/next"})))
    netguard.check_redirects("https://a.example/start")
    assert len(n) == netguard.MAX_HOPS
