import argparse
import json

from sqlalchemy import select

from triagedesk.config import settings
from triagedesk.db import engine, session_scope


def main():
    parser = argparse.ArgumentParser(
        prog="triagedesk", description="Private, explicit offline jobs for TriageDesk"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo-init")
    commands.add_parser("seed-fixtures")
    for name in ["import", "sync"]:
        p = commands.add_parser(name)
        p.add_argument("repository")
        p.add_argument(
            "--limit", type=int, default=2000, help="Maximum REST response objects including excluded PRs"
        )
    p = commands.add_parser("audit")
    p.add_argument("repositories", nargs="+")
    p.add_argument("--sample", type=int, default=200)
    p.add_argument("--out", default="data/repository-audit.json")
    p = commands.add_parser("prepare")
    p.add_argument("repository")
    p.add_argument("--mapping", default="config/labels.v1.yaml")
    p.add_argument("--out", default="data/dataset.json")
    p = commands.add_parser("train")
    p.add_argument("dataset")
    p.add_argument("--version", required=True)
    p = commands.add_parser("evaluate")
    p.add_argument("version", help="Report an already sealed evaluation; does not retune or resplit")
    p = commands.add_parser("activate")
    p.add_argument("version")
    p = commands.add_parser("index")
    p.add_argument("--semantic", action="store_true")
    p.add_argument(
        "--allow-download", action="store_true", help="Explicitly allow one-time pinned model download"
    )
    commands.add_parser("predict")
    p = commands.add_parser("benchmark")
    p.add_argument("--requests", type=int, default=100)
    p.add_argument("--api-url", default=None)
    p = commands.add_parser("review-dataset")
    p.add_argument("--out", default="data/future-reviewed-dataset.json")
    p = commands.add_parser("retrieval-pool")
    p.add_argument("--queries", type=int, default=40)
    p.add_argument("--out", default="data/retrieval-pool.json")
    p = commands.add_parser("evaluate-retrieval")
    p.add_argument("judgments", help="Completed frozen retrieval pool JSON, with human judgments")
    p = commands.add_parser("mark-unavailable")
    p.add_argument("issue_id", type=int)
    args = parser.parse_args()
    try:
        result = run(args)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        parser.exit(1, f"TriageDesk: {exc}\n")
    if result is not None:
        print(json.dumps(result, indent=2, default=str))


def run(args):
    command = args.command
    if command in {"seed-fixtures", "demo-init"}:
        if settings().mode != "fixture":
            if command == "demo-init":
                return {"status": "real mode; no synthetic data or automatic training seeded"}
            raise ValueError("Set MODE=fixture to load the synthetic demo")
        from triagedesk.fixtures import seed
        from triagedesk.retrieval import build_index

        with session_scope() as session:
            result = seed(session)
        with session_scope() as session:
            result["retrieval"] = build_index(session)
        return result
    if command in {"import", "sync"}:
        from triagedesk.github import ingest

        return ingest(engine(), args.repository, args.limit, incremental=command == "sync")
    if command == "audit":
        from triagedesk.audit import audit_repositories

        return audit_repositories(args.repositories, args.sample, args.out)
    if command == "prepare":
        from triagedesk.dataset import prepare_dataset

        with session_scope() as session:
            return prepare_dataset(session, args.repository, args.mapping, args.out)
    if command == "train":
        from triagedesk.training import train

        return train(args.dataset, args.version)
    if command == "evaluate":
        from triagedesk.artifacts import safe_version

        return json.loads(
            (settings().artifact_dir / "models" / safe_version(args.version) / "evaluation.json").read_text()
        )
    if command == "activate":
        from triagedesk.serving import activate

        return activate(args.version)
    if command == "index":
        from triagedesk.retrieval import build_index

        with session_scope() as session:
            return build_index(session, args.semantic, args.allow_download)
    if command == "predict":
        from triagedesk.models import Issue, Prediction, Repository
        from triagedesk.serving import classify_text, current_model

        if settings().mode != "real":
            raise ValueError(
                "Batch predictions require MODE=real; fixtures already contain illustrative suggestions"
            )
        _, report = current_model()
        predicted = 0
        with session_scope() as session:
            issues = session.scalars(
                select(Issue)
                .join(Repository, Repository.id == Issue.repository_id)
                .where(
                    Repository.synthetic.is_(False),
                    Repository.full_name == report["repository"],
                    Issue.available.is_(True),
                )
            )
            for issue in issues:
                prediction = classify_text(issue.title, issue.body)
                if not prediction["available"]:
                    raise ValueError(prediction["reason"])
                existing = session.scalar(
                    select(Prediction.id).where(
                        Prediction.snapshot_id == issue.snapshot_id,
                        Prediction.model_version == prediction["model_version"],
                    )
                )
                if existing:
                    continue
                session.add(
                    Prediction(
                        issue_id=issue.id,
                        snapshot_id=issue.snapshot_id,
                        input_hash=issue.content_hash,
                        **{
                            k: prediction[k]
                            for k in ["category", "scores", "max_score", "needs_review", "model_version"]
                        },
                    )
                )
                predicted += 1
        return {"predicted": predicted}
    if command == "benchmark":
        from triagedesk.benchmark import benchmark

        return benchmark(args.requests, args.api_url)
    if command == "review-dataset":
        from triagedesk.dataset import reviewed_dataset

        with session_scope() as session:
            return reviewed_dataset(session, args.out)
    if command == "retrieval-pool":
        from triagedesk.retrieval_eval import create_pool

        with session_scope() as session:
            return create_pool(session, args.queries, args.out)
    if command == "evaluate-retrieval":
        from triagedesk.retrieval_eval import evaluate_pool

        return evaluate_pool(args.judgments)
    if command == "mark-unavailable":
        from triagedesk.models import Issue

        with session_scope() as session:
            issue = session.get(Issue, args.issue_id)
            if not issue:
                raise ValueError("Unknown internal issue ID")
            issue.available = False
        return {"unavailable_issue": args.issue_id, "history_preserved": True}
