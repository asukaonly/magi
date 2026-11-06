"""Published model prices and the conditions under which they apply."""

from datetime import date
from typing import Annotated, Literal
from typing_extensions import TypedDict

from pydantic import AwareDatetime, BaseModel, Field, model_validator

Rate = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class LLMRateOverrides(TypedDict, total=False):
    """Omitted prices inherit; explicit null makes the price unknown."""

    currency: str | None
    input_per_million_tokens: Rate | None
    cached_input_per_million_tokens: Rate | None
    cache_write_per_million_tokens: Rate | None
    cache_write_1h_per_million_tokens: Rate | None
    cache_write_12h_per_million_tokens: Rate | None
    output_per_million_tokens: Rate | None
    cache_storage_per_million_token_hours: Rate | None
    per_image: Rate | None


class LLMTokenRates(BaseModel):
    currency: str | None = None
    input_per_million_tokens: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cached_input_per_million_tokens: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cache_write_per_million_tokens: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cache_write_1h_per_million_tokens: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cache_write_12h_per_million_tokens: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    output_per_million_tokens: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cache_storage_per_million_token_hours: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    per_image: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class LLMPricingRule(BaseModel):
    """Matching rules override rates in order; multipliers compose afterward."""

    min_input_tokens: int | None = Field(default=None, ge=0)
    max_input_tokens: int | None = Field(default=None, ge=0)
    min_output_tokens: int | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=0)
    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    endpoint_hosts: list[str] = Field(default_factory=list)
    service_tiers: list[str] = Field(default_factory=list)
    thinking: bool | None = None
    cache_mode: Literal["implicit", "explicit"] | None = None
    inference_geo: str | None = None
    rates: LLMRateOverrides = Field(default_factory=dict)
    multiplier: float = Field(default=1, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_ranges(self) -> "LLMPricingRule":
        for minimum, maximum in ((self.min_input_tokens, self.max_input_tokens),
                                 (self.min_output_tokens, self.max_output_tokens)):
            if minimum is not None and maximum is not None and minimum > maximum:
                raise ValueError("Pricing token range must be ordered")
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValueError("Pricing date range must be ordered")
        return self


class LLMPeakPricing(BaseModel):
    """UTC weekday peak windows, excluding published Chinese holiday dates."""

    utc_windows: list[tuple[int, int]]
    multiplier: float = Field(gt=0, allow_inf_nan=False)
    calendar_years: list[int]
    holidays: list[tuple[date, date]]
    sources: list[str]

    @model_validator(mode="after")
    def validate_calendar(self) -> "LLMPeakPricing":
        if any(not 0 <= start < end <= 1440 for start, end in self.utc_windows):
            raise ValueError("Peak windows must be ordered UTC minutes within one day")
        if any(start > end or start.year not in self.calendar_years or end.year not in self.calendar_years
               for start, end in self.holidays):
            raise ValueError("Holiday ranges must belong to the published calendar years")
        return self


class LLMModelCostModel(LLMTokenRates):
    """Provider-published prices; absent rates mean unknown, never free."""

    currency: str = "USD"
    source: str | None = None
    source_note: str | None = None
    verified_on: date | None = None
    endpoint_hosts: list[str] = Field(default_factory=list)
    rules: list[LLMPricingRule] = Field(default_factory=list)
    peak_pricing: LLMPeakPricing | None = None
