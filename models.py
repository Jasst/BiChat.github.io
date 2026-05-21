"""models.py — Pydantic модели для валидации"""
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime


class AddressMixin:
    """Валидация адреса"""

    @validator('address')
    def validate_address(cls, v):
        if len(v) != 64 or not all(c in '0123456789abcdef' for c in v):
            raise ValueError('Address must be 64 hex characters')
        return v.lower()


class LoginRequest(BaseModel):
    """Запрос на вход"""
    address: str
    public_key: str
    signature: str
    nonce: str


class CreateWalletRequest(BaseModel):
    """Создание кошелька"""
    address: str
    public_key: str


class SendMessageRequest(BaseModel):
    """Отправка сообщения"""
    recipient: str
    payload: Dict[str, Any]
    message_type: str = Field(default='direct')
    group_id: Optional[str] = None
    encrypted_map: Optional[Dict[str, str]] = None

    @validator('recipient')
    def validate_recipient(cls, v):
        if len(v) != 64 and not v.startswith('group:'):
            raise ValueError('Invalid recipient')
        return v


class CreateGroupRequest(BaseModel):
    """Создание группы"""
    name: str = Field(..., min_length=1, max_length=100)
    members: List[str] = Field(..., max_items=50)

    @validator('members', each_item=True)
    def validate_member(cls, v):
        if len(v) != 64:
            raise ValueError('Invalid member address')
        return v


class AddContactRequest(BaseModel):
    """Добавление контакта"""
    address: str
    name: str = Field(..., min_length=1, max_length=50)

    @validator('address')
    def validate_address(cls, v):
        if len(v) != 64:
            raise ValueError('Invalid address')
        return v


class TransferRequest(BaseModel):
    """Перевод монет"""
    recipient: str
    amount: int = Field(..., gt=0)

    @validator('recipient')
    def validate_recipient(cls, v):
        if len(v) != 64:
            raise ValueError('Invalid recipient address')
        return v


class StakeRequest(BaseModel):
    """Стейкинг"""
    amount: int = Field(..., gt=0)


class MineRequest(BaseModel):
    """Майнинг"""
    proof: int
    challenge: str
    last_proof: int
    last_index: int


class MessageResponse(BaseModel):
    """Ответ с сообщением"""
    id: int
    sender: str
    recipient: str
    content: Optional[str] = None
    image: Optional[str] = None
    timestamp: float
    is_mine: bool = False


class ContactResponse(BaseModel):
    """Ответ с контактом"""
    address: str
    name: str
    pubkey: Optional[str] = None
    pubkey_verified: bool = False
    created_at: Optional[str] = None


class GroupResponse(BaseModel):
    """Ответ с группой"""
    id: str
    name: str
    creator: str
    members: List[str]
    member_count: int
    created_at: Optional[str] = None


class BalanceResponse(BaseModel):
    """Ответ с балансом"""
    address: str
    balance: int
    staked: int
    coin: int
    coin_name: str


class TransactionResponse(BaseModel):
    """Ответ с транзакцией"""
    id: int
    type: str
    sender: Optional[str]
    recipient: str
    amount: int
    timestamp: float


class StatusResponse(BaseModel):
    """Ответ со статусом"""
    address: str
    status: str
    last_seen: Optional[str] = None
    current_chat: Optional[str] = None


# Вспомогательные функции для валидации
def validate_address(address: str) -> bool:
    """Проверяет валидность адреса"""
    return len(address) == 64 and all(c in '0123456789abcdef' for c in address)


def validate_group_id(group_id: str) -> bool:
    """Проверяет валидность ID группы"""
    return len(group_id) == 32 and all(c in '0123456789abcdef' for c in group_id)