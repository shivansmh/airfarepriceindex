import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def github_json(url: str, token: str):
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "airfarepriceindex-system-logs",
        },
    )
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def main(output_path: str):
    token = os.environ.get("GITHUB_TOKEN")
    repository = os.environ.get("GITHUB_REPOSITORY", "shivansmh/airfarepriceindex")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set")

    api_base = f"https://api.github.com/repos/{repository}"
    runs = github_json(f"{api_base}/actions/runs?per_page=20", token).get("workflow_runs", [])
    records = []
    for run in runs:
        run_id = run["id"]
        try:
            jobs = github_json(f"{api_base}/actions/runs/{run_id}/jobs?per_page=100", token).get("jobs", [])
        except (HTTPError, URLError):
            jobs = []
        records.append(
            {
                "id": run_id,
                "workflow": run.get("name", "Unknown workflow"),
                "title": run.get("display_title") or run.get("name", "Untitled run"),
                "event": run.get("event", "unknown"),
                "status": run.get("status", "unknown"),
                "conclusion": run.get("conclusion"),
                "created_at": run.get("created_at"),
                "updated_at": run.get("updated_at"),
                "url": run.get("html_url"),
                "sha": (run.get("head_sha") or "")[:7],
                "jobs": [
                    {
                        "name": job.get("name", "Unknown job"),
                        "status": job.get("status", "unknown"),
                        "conclusion": job.get("conclusion"),
                        "started_at": job.get("started_at"),
                        "completed_at": job.get("completed_at"),
                        "steps": [
                            {
                                "name": step.get("name", "Unknown step"),
                                "status": step.get("status", "unknown"),
                                "conclusion": step.get("conclusion"),
                            }
                            for step in job.get("steps", [])
                        ],
                    }
                    for job in jobs
                ],
            }
        )

    payload = {
        "repository": repository,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runs": records,
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[Success] Exported {len(records)} GitHub Actions runs to {destination}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dashboard/system_logs.json")
