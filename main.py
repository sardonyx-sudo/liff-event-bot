import os
import sys
import requests
from fastapi import FastAPI, Request, HTTPException, Depends, Header
from typing import Optional
from pydantic import BaseModel
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, PostbackEvent
from config import config
from database import db_service
from models import User, Event, EventStatus 

app = FastAPI()

# LINE Bot 初始化
line_bot_api = LineBotApi(config.LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(config.LINE_CHANNEL_SECRET)

@app.get("/")
def health_check():
    return {"status": "ok", "service": "Line Bot Attendance"}

# LINE Webhook 入口
@app.post("/callback")
async def callback(request: Request):
    signature = request.headers.get('X-Line-Signature', '')
    body = await request.body()
    body_str = body.decode('utf-8')

    try:
        handler.handle(body_str, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    return "OK"

# --- 1. 安全性驗證 (Dependency) ---

async def verify_admin_token(authorization: Optional[str] = Header(None)):
    """
    驗證 LIFF 傳來的 ID Token
    1. 檢查 Token 是否有效
    2. 檢查該 User 是否為 Admin
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization Header")
    
    token = authorization.replace("Bearer ", "")
    
    # 呼叫 LINE Verify API
    verify_url = "https://api.line.me/oauth2/v2.1/verify"
    response = requests.post(verify_url, data={
        "id_token": token,
        "client_id": config.LIFF_ID_ADMIN  # 需在 .env 設定管理員 LIFF ID
    })
    
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Token")
    
    user_data = response.json()
    line_uid = user_data.get('sub')
    
    # 檢查是否為系統管理員
    db_user = db_service.get_user(line_uid)
    if not db_user or not db_user.get('is_admin'):
        raise HTTPException(status_code=403, detail="Permission Denied: Not Admin")
    
    return db_user # 回傳使用者資料供 API 使用

# --- 2. Admin API Routes ---

# 取得活動列表 (包含草稿與已發佈，供管理)
@app.get("/api/admin/events")
def list_events(user = Depends(verify_admin_token)):
    # 這裡簡單實作：回傳草稿 + 未來已發佈的活動
    drafts = db_service.get_draft_events()
    return {"events": drafts}

# 建立活動
@app.post("/api/admin/events")
def create_event_api(event: Event, user = Depends(verify_admin_token)):
    # 強制設定建立時間與狀態
    event_dict = event.model_dump()
    event_id = db_service.create_event(event_dict)
    return {"status": "success", "id": event_id}

# 修改活動
@app.put("/api/admin/events/{event_id}")
def update_event_api(event_id: str, event: Event, user = Depends(verify_admin_token)):
    # 排除 None 的欄位，避免覆蓋掉原本的資料 (視需求而定)
    update_data = {k: v for k, v in event.model_dump().items() if v is not None}
    db_service.update_event(event_id, update_data)
    return {"status": "success"}

# 取得成員列表 (供排序與管理)
@app.get("/api/admin/members")
def list_members(user = Depends(verify_admin_token)):
    members = db_service.get_all_members()
    return {"members": members}

# 更新成員資料 (排序/狀態)
class MemberUpdateReq(BaseModel):
    sort_order: Optional[int] = None
    status: Optional[str] = None
    club_name: Optional[str] = None
    is_admin: Optional[bool] = None

@app.put("/api/admin/members/{user_id}")
def update_member_api(user_id: str, req: MemberUpdateReq, user = Depends(verify_admin_token)):
    update_data = {k: v for k, v in req.model_dump().items() if v is not None}
    db_service.update_member_status(user_id, update_data)
    return {"status": "success"}

# --- 事件處理邏輯 ---

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text.strip()
    user_id = event.source.user_id
    profile = line_bot_api.get_profile(user_id)
    
    # 1. 自動建檔 / 更新資料
    user_data = db_service.upsert_user(profile)

    # 2. 管理員認證流程
    if msg == "我是管理員":
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請輸入啟動碼：")
        )
        return

    # 3. 檢查是否為啟動碼
    # 這裡做一個簡單的邏輯：如果上一句是系統問啟動碼 (可用 Cache 存狀態，這邊先簡化直接判斷內容)
    # 為了簡化，直接判斷如果 msg 等於啟動碼就升級
    if db_service.verify_admin_code(user_id, msg):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="✅ 認證成功！您已成為管理員。\n請重新開啟 Rich Menu 使用管理功能。")
        )
        return

    # 4. 其他群組文字訊息 -> 忽略 (符合您的需求)
    if event.source.type == "group":
        return

@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    user_id = event.source.user_id
    
    # 這裡之後會實作 +1 / -1 / 重發 / 下個活動 的邏輯
    # Step 2 會詳細填寫這邊
    print(f"Received Postback: {data} from {user_id}")
    pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)