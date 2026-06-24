from typing import Literal

from pydantic import BaseModel, Field


class OrderRequest(BaseModel):
    user_id: str
    market_id: int
    outcome: Literal["YES", "NO"] = "YES"
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)


class LimitOrderRequest(OrderRequest):
    side: Literal["BUY", "SELL"]


class MergeRequest(BaseModel):
    user_id: str
    source_market_id: int
    target_market_id: int
    source_outcome: Literal["YES", "NO"] = "YES"
    target_outcome: Literal["YES", "NO"] = "NO"
    quantity: float = Field(gt=0)


class SplitRequest(BaseModel):
    user_id: str
    market_id: int
    source_type: str
    left_type: str
    right_type: str
    ratio_left: float = Field(gt=0)
    ratio_right: float = Field(gt=0)
    quantity: float = Field(gt=0)


class PaymentRequest(BaseModel):
    user_id: str
    asset: str = Field(min_length=2, max_length=10)
    amount: float = Field(gt=0)
    reference: str | None = None


class OnboardingRequest(BaseModel):
    user_id: str
    wallet_address: str
    user_name: str = Field(min_length=2, max_length=80)
    user_profile: str = Field(default="", max_length=500)
    profile_picture: str | None = None


class LocalSignupRequest(BaseModel):
    email: str = Field(min_length=5, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    user_name: str = Field(min_length=2, max_length=80)
    user_profile: str = Field(default="", max_length=500)
    solana_wallet_address: str = Field(default="", max_length=120)
    profile_picture: str | None = None


class LocalSigninRequest(BaseModel):
    email: str = Field(min_length=5, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class AdminAdjustBalanceRequest(BaseModel):
    admin_user_id: str
    target_user_id: str
    asset: str = Field(min_length=2, max_length=20)
    delta: float
    reason: str = Field(min_length=3, max_length=200)


class AdminFreezeRequest(BaseModel):
    admin_user_id: str
    target_user_id: str
    freeze: bool
    reason: str = Field(min_length=3, max_length=200)


class AdminSetRoleRequest(BaseModel):
    admin_user_id: str
    target_user_id: str
    is_admin: bool


class AdminAccessGrantRequest(BaseModel):
    email: str = Field(min_length=5, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class AdminAuthenticatedRequest(BaseModel):
    admin_email: str = Field(min_length=5, max_length=200)
    admin_password: str = Field(min_length=1, max_length=200)


class AdminCreateMarketRequest(AdminAuthenticatedRequest):
    symbol: str = Field(min_length=2, max_length=30)
    name: str = Field(min_length=2, max_length=120)
    question: str = Field(default="", max_length=240)
    description: str = Field(default="", max_length=1000)
    tick_size: float = Field(gt=0)
    min_order_size: float = Field(gt=0)


class AdminMarketStatusRequest(AdminAuthenticatedRequest):
    status: Literal["OPEN", "PAUSED", "CLOSED"]


class AdminStaleCleanupRequest(AdminAuthenticatedRequest):
    max_age_minutes: int = Field(gt=0, le=10080)
    market_id: int | None = None


class AdminReconcileRequest(AdminAuthenticatedRequest):
    market_id: int | None = None


class AdminRiskRecalcRequest(AdminAuthenticatedRequest):
    limit: int = Field(default=20, gt=0, le=100)
