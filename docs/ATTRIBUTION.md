# Attribution and integration references

Official documentation checked during implementation on 26 October 2026:

- [GitHub repository issues REST API](https://docs.github.com/en/rest/issues/issues): both states, PR identification, update-time `since`, pagination.
- [GitHub REST best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api): serial calls, bounded retries, rate/reset headers and conditional requests.
- [Python supported versions](https://devguide.python.org/versions/): Python 3.12 security support through October 2028.
- [uv project locking](https://docs.astral.sh/uv/guides/projects/) and [CPU PyTorch sources](https://docs.astral.sh/uv/guides/integration/pytorch/).
- [FastAPI containers](https://fastapi.tiangolo.com/deployment/docker/), [SQLAlchemy transactions/version counters](https://docs.sqlalchemy.org/en/20/orm/versioning.html), [Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html), [Streamlit running apps](https://docs.streamlit.io/develop/concepts/architecture/run-your-app).
- [scikit-learn LogisticRegression](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html).
- [MiniLM model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2), pinned [revision](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/c9745ed1d9f207416be6d2e6f8de32d1f16199bf): Apache-2.0, 384 dimensions, 256-wordpiece truncation. License and exact SHA were verified using the model metadata endpoint.
- [Render Blueprint reference](https://render.com/docs/blueprint-spec), [pricing](https://render.com/pricing), [compute plans](https://render.com/docs/compute-plans), [persistent disks](https://render.com/docs/disks), [backups](https://render.com/docs/postgresql-backups), [health checks](https://render.com/docs/health-checks), [SSH](https://render.com/docs/ssh).

Actual source reports retain GitHub URLs in database snapshots and artifact manifests. Issues belong to their original authors; project-code licensing does not automatically cover their text. The synthetic fixture is invented for this project. Codex assisted implementation and verification; personal user review and maintainer usability validation are still pending (see interview preparation).
