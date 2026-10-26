from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Category = Literal["bug", "enhancement", "question"]


class IssueFilters(BaseModel):
    repository_id: int | None = None
    created_from: datetime | None = None
    created_before: datetime | None = None
    category: Category | None = None
    category_source: Literal["effective", "predicted", "reviewed"] = "effective"
    state: Literal["open", "closed"] | None = None
    review_status: Literal["awaiting", "reviewed", "deferred", "skipped"] | None = None
    search: str = Field("", max_length=200)
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    sort: Literal["oldest", "newest", "lowest_score"] = "oldest"

    @model_validator(mode="after")
    def dates(self):
        for name in ("created_from", "created_before"):
            value = getattr(self, name)
            if value and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("Date filters must include a timezone")
        if self.created_from and self.created_before and self.created_from >= self.created_before:
            raise ValueError("created_from must precede created_before")
        return self


class TextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    body: str = Field("", max_length=50000)
    repository_id: int | None = None


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept", "correct", "defer", "skip"]
    category: Category | None = None
    note: str = Field("", max_length=2000)
    prediction_id: int | None = None
    snapshot_id: int
    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @model_validator(mode="after")
    def category_for_action(self):
        if (self.action in {"accept", "correct"}) != (self.category is not None):
            raise ValueError("accept/correct require a category; defer/skip must omit it")
        if self.action == "accept" and self.prediction_id is None:
            raise ValueError("Accept requires a prediction; use correct to categorize manually")
        return self


class JudgmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_issue_id: int
    query_snapshot_id: int
    candidate_snapshot_id: int
    judgment: Literal["related", "duplicate", "unrelated", "uncertain"]
    idempotency_key: str = Field(min_length=8, max_length=100)


class Suggestion(BaseModel):
    available: bool
    category: Category | None = None
    scores: dict[str, float] = Field(default_factory=dict)
    max_score: float | None = None
    needs_review: bool = True
    model_version: str | None = None
    reason: str | None = None
    score_meaning: str = "Model scores are not calibrated probabilities"


class RepositoryOut(BaseModel):
    id: int
    full_name: str
    source_url: str
    partial: bool
    synthetic: bool
    last_synced_at: datetime | None
    checkpoint: datetime | None


class PredictionOut(BaseModel):
    id: int
    category: Category
    scores: dict[str, float]
    max_score: float
    needs_review: bool
    model_version: str
    created_at: datetime
    input_hash: str


class IssueSummary(BaseModel):
    id: int
    repository_id: int
    number: int
    title: str
    source_url: str
    state: Literal["open", "closed"]
    created_at: datetime
    updated_at: datetime
    snapshot_id: int
    review_revision: int
    prediction_id: int | None
    predicted_category: Category | None
    reviewed_category: Category | None
    max_score: float | None
    needs_review: bool | None
    model_version: str | None
    review_status: Literal["awaiting", "reviewed", "deferred", "skipped"]
    review_complete: bool


class IssuePage(BaseModel):
    items: list[IssueSummary]
    total: int
    page: int
    page_size: int


class IssueDetail(IssueSummary):
    body: str
    labels: list[str]
    content_hash: str
    ingested_at: datetime
    closed_at: datetime | None
    prediction: PredictionOut | None


class SavedReview(BaseModel):
    id: int
    revision: int
    action: Literal["accept", "correct", "defer", "skip"]
    category: Category | None
    created_at: datetime


class ReviewHistory(SavedReview):
    snapshot_id: int
    prediction_id: int | None
    note: str
    reviewer: str


class RelatedIssue(BaseModel):
    id: int
    snapshot_id: int
    number: int
    title: str
    excerpt: str
    source_url: str
    state: Literal["open", "closed"]
    score: float


class RelatedResults(BaseModel):
    items: list[RelatedIssue]
    method: Literal["unavailable", "tfidf", "semantic"]
    message: str


class DashboardSummary(BaseModel):
    imported: int
    open: int
    closed: int
    reviewed: int
    low_score: int
    awaiting_review: int
    review_completion_rate: float
    predicted_categories: dict[str, int]
    reviewed_categories: dict[str, int]
    arrivals: list[dict[str, str | int]]
    recent_reviews: list[dict]
    scope: str


class SavedJudgment(BaseModel):
    id: int
    judgment: Literal["related", "duplicate", "unrelated", "uncertain"]
    purpose: Literal["ui"]


class ModelSummary(BaseModel):
    status: str
    classification: dict | None
    retrieval: dict | None
    benchmark: dict | None
