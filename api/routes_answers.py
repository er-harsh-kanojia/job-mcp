"""Answer bank: your saved answers to application questions, and questions waiting for one."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from tools import answers

from .errors import ApiError, not_found

router = APIRouter(prefix="/api")


class AnswerBody(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    answer: str = Field(min_length=1, max_length=2000)


class AnswerText(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)


@router.get("/answers")
async def get_answers():
    """Saved answers (newest first) and questions waiting for your answer (most frequent first)."""
    return {"answers": answers.list_answers(), "pending": answers.list_pending()}


@router.post("/answers")
async def add_answer(body: AnswerBody):
    saved = answers.save(body.question, body.answer, source="manual")
    if saved is None:
        raise ApiError(422, "validation", "Question and answer must not be empty.")
    return saved


@router.put("/answers/{answer_id}")
async def edit_answer(answer_id: int, body: AnswerText):
    saved = answers.update(answer_id, body.answer)
    if saved is None:
        raise not_found("Answer not found.")
    return saved


@router.delete("/answers/{answer_id}")
async def delete_answer(answer_id: int):
    if not answers.delete(answer_id):
        raise not_found("Answer not found.")
    return {"ok": True}


@router.post("/answers/pending/{pending_id}")
async def answer_pending(pending_id: int, body: AnswerText):
    """Answer a waiting question once; it moves to the saved answers and is reused from now on."""
    saved = answers.resolve_pending(pending_id, body.answer)
    if saved is None:
        raise not_found("Question not found.")
    return saved


@router.delete("/answers/pending/{pending_id}")
async def dismiss_pending(pending_id: int):
    if not answers.dismiss_pending(pending_id):
        raise not_found("Question not found.")
    return {"ok": True}
