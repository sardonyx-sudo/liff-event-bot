from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum
from datetime import datetime

# --- Enums 保持不變 ---
class UserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    LEAVE = "LEAVE"

class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    FINISHED = "FINISHED" # 結束 (計入出席率)
    CANCELED = "CANCELED" # 取消 (不計入)

class ParticipantStatus(str, Enum):
    GOING = "GOING"
    NOT_GOING = "NOT_GOING"

# --- Models ---

class Guest(BaseModel):
    name: str
    adults: int = 1
    kids: int = 0

class User(BaseModel):
    line_id: str
    display_name: str
    club_name: Optional[str] = None
    is_admin: bool = False
    status: UserStatus = UserStatus.ACTIVE
    sort_order: int = 999

# 修正後的 Event 模型
class Event(BaseModel):
    id: Optional[str] = None
    type: str                  # 例會, 聯誼...
    title: str                 # 活動主題
    event_date: str            # YYYY-MM-DD (日期分開)
    event_time: str            # HH:MM (時間分開)
    location: str
    
    # 選填欄位 (依據之前需求保留)
    talk_title: Optional[str] = None  # 講題
    speaker: Optional[str] = None     # 講師
    description: Optional[str] = None # 備註 (對應 note)
    
    status: EventStatus = EventStatus.DRAFT
    created_at: datetime = datetime.now()

class Attendance(BaseModel):
    user_id: str
    user_name: str
    status: ParticipantStatus
    family_adults: int = 0
    family_kids: int = 0
    guests: List[Guest] = []
    updated_at: datetime = datetime.now()