# Attribution

The project code is licensed under the [MIT License](../LICENSE).

## Issue data

The offline classifier experiments use public issues from [microsoft/vscode](https://github.com/microsoft/vscode/issues). A separate retrieval collection also includes [streamlit/streamlit](https://github.com/streamlit/streamlit/issues). Source URLs and snapshot identities are retained in generated datasets and manifests.

Issue text belongs to its original authors. The project license does not relicense that text. Raw issue corpora and database backups are not included in this source repository. The built-in demo uses synthetic issues written for this project.

See [DATA_CARD.md](DATA_CARD.md) for collection details and limitations.

## Optional embedding model

Semantic retrieval uses [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2), pinned to revision `c9745ed1d9f207416be6d2e6f8de32d1f16199bf`. The model is licensed under Apache-2.0. Its weights are downloaded separately when explicitly enabled.

## Integration references

- [GitHub issues REST API](https://docs.github.com/en/rest/issues/issues)
- [GitHub REST API best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)
- [Groq structured outputs](https://console.groq.com/docs/structured-outputs)
- [Streamlit deployment](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app)
- [SQLAlchemy transactions](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html)
- [Alembic migrations](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- [scikit-learn LogisticRegression](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html)
- [uv project dependencies](https://docs.astral.sh/uv/guides/projects/)
