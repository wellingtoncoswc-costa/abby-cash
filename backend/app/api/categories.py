from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Session
from app.api.schemas import CategoryOut
from app.core.serialize import row
from app.domain.categories.service import (
    create_category,
    delete_category,
    list_categories,
    update_category,
)

router = APIRouter(tags=["categories"])
Name = Annotated[str, Field(min_length=1, max_length=60)]


class CategoryIn(BaseModel):
    name: Name
    kind: Literal["expense", "income"]
    icon: str | None = Field(default=None, max_length=32)
    color: str | None = Field(default=None, max_length=16)


class CategoryPatch(BaseModel):
    name: Name | None = None
    icon: str | None = Field(default=None, max_length=32)
    color: str | None = Field(default=None, max_length=16)


@router.get("/spaces/{space_id}/categories", response_model=list[CategoryOut])
async def list_(space_id: UUID, user: CurrentUser, session: Session) -> list[dict[str, object]]:
    return [row(c) for c in await list_categories(session, viewer_id=user.id, space_id=space_id)]


@router.post("/spaces/{space_id}/categories", status_code=201, response_model=CategoryOut)
async def create(
    space_id: UUID, body: CategoryIn, user: CurrentUser, session: Session
) -> dict[str, object]:
    cat = await create_category(
        session, actor_id=user.id, space_id=space_id, kind=body.kind, name=body.name,
        icon=body.icon, color=body.color,
    )  # fmt: skip
    return row(cat)


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def patch(
    category_id: UUID, body: CategoryPatch, user: CurrentUser, session: Session
) -> dict[str, object]:
    fields = body.model_dump(exclude_unset=True)
    if fields.get("name", "x") is None:
        fields.pop("name")
    return row(
        await update_category(session, actor_id=user.id, category_id=category_id, fields=fields)
    )


@router.delete("/categories/{category_id}", status_code=204)
async def delete(
    category_id: UUID,
    user: CurrentUser,
    session: Session,
    reassign_to: Annotated[UUID | None, Query()] = None,
) -> None:
    await delete_category(
        session, actor_id=user.id, category_id=category_id, reassign_to=reassign_to
    )
