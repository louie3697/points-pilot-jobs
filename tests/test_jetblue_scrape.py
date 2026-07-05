import yaml

_WF = ".github/workflows/jetblue-scrape.yml"


def test_jetblue_scrape_imports_and_configures():
    import jetblue_scrape
    # POI-20 lever #3: bumped 30→36 for the expanded Mint business route set.
    assert jetblue_scrape.MAX_LEGS_PER_SHARD == 36
    from scrapers.jetblue import JetBlueScraper
    assert JetBlueScraper.airline_code == "B6"


def test_jetblue_workflow_runs_daily_probe_while_blocked():
    """JetBlue is currently 100% blocked on GitHub Actions HTTP 406, so keep a daily low-rate
    health probe instead of three 5-shard coverage pushes."""
    with open(_WF) as f:
        wf = yaml.safe_load(f)
    # PyYAML parses the bare `on:` key as the boolean True.
    schedule = wf[True]["schedule"]
    crons = [s["cron"] for s in schedule]
    assert crons == ["37 20 * * *"]
    hour = int(crons[0].split()[1])
    assert not (8 <= hour <= 11), "cron must avoid the 08–11 UTC award block"


def test_jetblue_workflow_shard_matrix_is_consistent():
    """JetBlue uses a one-shard, one-route, one-date daily probe while HTTP 406 remains blocked."""
    with open(_WF) as f:
        wf = yaml.safe_load(f)
    job = wf["jobs"]["scrape"]
    shards = job["strategy"]["matrix"]["shard"]
    env = job["steps"][-1]["env"]
    n = int(env["JETBLUE_SHARDS"])
    assert shards == list(range(n)), f"matrix {shards} must be range(JETBLUE_SHARDS={n})"
    assert n == 1, "JetBlue runs one-shard daily probe while HTTP 406 blocked"
    assert (
        env["JETBLUE_SCRAPE_DAYS"] == "1"
    ), "JetBlue uses one-date probes while HTTP 406 is blocked"
    assert env["JETBLUE_MAX_LEGS_PER_SHARD"] == "1"
    assert env["JETBLUE_SHARD_INDEX"] == "${{ matrix.shard }}"
