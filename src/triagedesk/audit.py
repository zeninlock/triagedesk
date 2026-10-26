from collections import Counter

from triagedesk.artifacts import write_json
from triagedesk.github import GitHubClient, valid_repository
from triagedesk.models import utcnow
from triagedesk.text import label_mapping, map_labels


def audit_repositories(names, sample, out):
    if not 2 <= sample <= 1000:
        raise ValueError("Audit sample must be between 2 and 1000 response objects per repository")
    mapping = label_mapping()
    results = []
    client = GitHubClient()
    try:
        for name in names:  # Deliberately serial, including across repositories.
            name = valid_repository(name)
            meta = client.get(f"/repos/{name}").json()
            search = client.get("/search/issues", params={"q": f"repo:{name} is:issue", "per_page": 1}).json()
            labels, path = [], f"/repos/{name}/labels?per_page=100"
            while path:
                response = client.get(path)
                labels.extend(label["name"] for label in response.json())
                path = response.links.get("next", {}).get("url")
            cohorts, seen, examples = {}, set(), []
            for cohort, sort, direction in [
                ("earliest_updated", "updated", "asc"),
                ("recent_created", "created", "desc"),
            ]:
                params = {
                    "state": "all",
                    "sort": sort,
                    "direction": direction,
                    "per_page": min(100, sample // 2),
                }
                response = client.get(f"/repos/{name}/issues", params=params)
                counts, label_counts, excluded_prs, fetched, ambiguous = Counter(), Counter(), 0, 0, 0
                for raw in response.json():
                    fetched += 1
                    if "pull_request" in raw:
                        excluded_prs += 1
                        continue
                    seen.add(raw["id"])
                    names_ = [label["name"] for label in raw["labels"]]
                    label_counts.update(names_)
                    category, status = map_labels(names_, name, mapping)
                    counts[category or status] += 1
                    ambiguous += status == "conflicting"
                    if len(examples) < 5 or len(examples) < 10 and cohort == "recent_created":
                        examples.append(
                            {
                                "number": raw["number"],
                                "title": raw["title"],
                                "labels": names_,
                                "created_at": raw["created_at"],
                                "updated_at": raw["updated_at"],
                                "url": raw["html_url"],
                            }
                        )
                cohorts[cohort] = {
                    "response_objects": fetched,
                    "pull_requests_excluded": excluded_prs,
                    "issues": fetched - excluded_prs,
                    "categories": dict(counts),
                    "labels": dict(label_counts),
                    "conflicts": ambiguous,
                }
            results.append(
                {
                    "repository": name,
                    "available_issues_search_count": search.get("total_count"),
                    "search_incomplete": search.get("incomplete_results"),
                    "open_issues_and_pull_requests_metadata": meta["open_issues_count"],
                    "label_names": labels,
                    "unique_sampled_issues": len(seen),
                    "cohorts": cohorts,
                    "examples_for_manual_language_template_audit": examples,
                }
            )
    finally:
        client.close()
    report = {
        "collected_at": utcnow(),
        "mapping_version": mapping["version"],
        "repositories": results,
        "limitations": [
            "Purposive oldest-updated and newest-created samples, not random estimates of class prevalence",
            "Labels are current, not historical; cohort differences cannot prove a convention change",
            "Language consistency and explicit category templates require inspecting actual sample text",
            "sample controls each cohort up to 100 objects; no more than 200 objects per repository in this small audit",
        ],
    }
    write_json(out, report)
    return {"report": out, "repositories": results}
