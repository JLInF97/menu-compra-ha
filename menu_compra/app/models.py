"""Validación de todas las entradas. Importes en céntimos de euro."""
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Name = Annotated[str, Field(min_length=1, max_length=180)]
Price = Annotated[int, Field(strict=True, ge=0, le=100_000_000)]
ID = Annotated[int, Field(gt=0, le=9_223_372_036_854_775_807)]
Quantity = Annotated[Decimal, Field(gt=0, le=100_000, max_digits=9, decimal_places=3, allow_inf_nan=False)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CategoryIn(Input):
    name: Name
    sort_order: int = Field(default=50, ge=0, le=10000)
    is_frozen: bool = False


class SupermarketIn(Input):
    name: Name


class ProductIn(Input):
    name: Name
    category_id: ID
    supermarket_id: ID
    unit: str = Field(default="ud", min_length=1, max_length=20)
    notes: str = Field(default="", max_length=4000)
    price_cents: Price


class PriceIn(Input):
    price_cents: Price


class ShoppingIn(Input):
    product_id: ID
    quantity: Quantity = Decimal("1")
    price_cents: Price | None = None
    note: str = Field(default="", max_length=1000)


class ShoppingPatch(Input):
    quantity: Quantity | None = None
    checked: bool | None = None
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def non_null(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Indica al menos un campo y no uses valores nulos")
        return self


class IngredientIn(Input):
    product_id: ID
    quantity: Quantity = Decimal("1")


class DishIn(Input):
    name: Name
    notes: str = Field(default="", max_length=4000)
    ingredients: list[IngredientIn] = Field(default_factory=list, max_length=100)

    @field_validator("ingredients")
    @classmethod
    def unique_products(cls, value):
        ids = [i.product_id for i in value]
        if len(ids) != len(set(ids)):
            raise ValueError("No repitas un producto en los ingredientes")
        return value


class MenuIn(Input):
    date: date
    slot: Literal["lunch", "dinner"]
    text: str = Field(default="", max_length=1000)
    dish_id: ID | None = None


class IngredientSelection(Input):
    product_ids: list[ID] = Field(max_length=100)

    @field_validator("product_ids")
    @classmethod
    def unique_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("No repitas ingredientes")
        return value


class MenuBatchIn(Input):
    date: date
    slot: Literal["lunch", "dinner"]
    texts: list[Name] = Field(min_length=1, max_length=20)


class MenuShoppingIn(Input):
    product_id: ID | None = None
    quantity: Quantity = Decimal("1")
    price_cents: Price | None = None
    note: str = Field(default="", max_length=1000)


class QuickShoppingIn(Input):
    name: Name
    product_id: ID | None = None
    quantity: Quantity = Decimal("1")
    price_cents: Price | None = None


class DuplicateWeekIn(Input):
    week: date


class ShoppingAdjustIn(Input):
    delta: Annotated[int, Field(strict=True)]

    @field_validator("delta")
    @classmethod
    def valid_delta(cls, value):
        if value not in (-1, 1):
            raise ValueError("El ajuste debe ser -1 o 1")
        return value
