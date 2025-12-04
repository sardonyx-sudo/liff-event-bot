import firebase_admin
from firebase_admin import credentials, firestore
from models import User, Event, Attendance, UserStatus, ParticipantStatus, EventStatus
from config import config
from datetime import datetime

# 初始化 Firestore
# 注意：在 Cloud Run 上不需要 creds，會自動抓取 Service Account
if not firebase_admin._apps:
    if config.GOOGLE_APPLICATION_CREDENTIALS:
        cred = credentials.Certificate(config.GOOGLE_APPLICATION_CREDENTIALS)
        firebase_admin.initialize_app(cred)
    else:
        firebase_admin.initialize_app()

db = firestore.client()

class Database:
    # --- 使用者管理 ---
    
    def get_user(self, line_id: str):
        doc = db.collection('users').document(line_id).get()
        if doc.exists:
            return doc.to_dict()
        return None

    def upsert_user(self, profile):
        """使用者第一次互動時建立資料，或更新基本資料"""
        user_ref = db.collection('users').document(profile.user_id)
        doc = user_ref.get()
        
        if not doc.exists:
            # 新使用者，預設排序為目前最大值 + 1
            max_order = self._get_max_sort_order()
            new_user = User(
                line_id=profile.user_id,
                display_name=profile.display_name,
                sort_order=max_order + 1
            )
            user_ref.set(new_user.model_dump())
            return new_user.model_dump()
        else:
            # 舊使用者，僅更新 LINE 暱稱 (不蓋掉社團暱稱)
            user_ref.update({"display_name": profile.display_name})
            return doc.to_dict()

    def _get_max_sort_order(self):
        """取得目前最大的排序值"""
        users = db.collection('users').order_by('sort_order', direction=firestore.Query.DESCENDING).limit(1).stream()
        for user in users:
            return user.to_dict().get('sort_order', 999)
        return 0

    def verify_admin_code(self, line_id: str, code: str):
        """驗證啟動碼並升級為管理員"""
        if code == config.ADMIN_SETUP_CODE:
            db.collection('users').document(line_id).update({"is_admin": True})
            return True
        return False

    def update_user_sort(self, line_id: str, new_order: int):
        """更新排序 (數字輸入用)"""
        # 這裡未來可以加入邏輯：如果數字重複，是否自動將其他人往後移
        # 目前先實作最簡單的更新
        db.collection('users').document(line_id).update({"sort_order": new_order})

    # --- 成員管理 (新增：供 Admin LIFF 使用) ---
    
    def get_all_members(self):
        """取得所有成員 (用於管理列表)"""
        # 依照 sort_order 排序
        docs = db.collection('users').order_by('sort_order').stream()
        return [doc.to_dict() for doc in docs]

    def update_member_status(self, user_id: str, updates: dict):
        """更新成員資料 (排序、狀態、暱稱)"""
        # updates 範例: {"sort_order": 5, "status": "LEAVE", "club_name": "社長"}
        db.collection('users').document(user_id).update(updates)

    # --- 活動管理 ---

    def create_event(self, event_data: dict):
        """建立新活動"""
        new_ref = db.collection('events').document()
        event_data['id'] = new_ref.id
        # 確保 status 為 DRAFT
        event_data['status'] = EventStatus.DRAFT.value 
        new_ref.set(event_data)
        return new_ref.id

    def update_event(self, event_id: str, event_data: dict):
        """修改活動"""
        db.collection('events').document(event_id).update(event_data)

    def get_event(self, event_id: str):
        doc = db.collection('events').document(event_id).get()
        return doc.to_dict() if doc.exists else None
    
    def get_draft_events(self):
        """取得所有草稿 (供 Admin 列表選擇編輯)"""
        docs = db.collection('events')\
            .where('status', '==', EventStatus.DRAFT.value)\
            .order_by('event_date')\
            .stream()
        return [doc.to_dict() for doc in docs]
    
    def get_next_draft_event(self):
        """
        取得「下一個」DRAFT 活動 (用於發佈)
        邏輯：因為 event_date 是字串 "YYYY-MM-DD"，可以直接用字串比對
        """
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        docs = db.collection('events')\
            .where('status', '==', EventStatus.DRAFT.value)\
            .where('event_date', '>=', today_str)\
            .order_by('event_date')\
            .order_by('event_time')\
            .limit(1).stream()
        
        for doc in docs:
            return doc.to_dict()
        return None

    # --- 報名與統計邏輯 (核心) ---

    def add_attendance(self, event_id: str, attendance: Attendance):
        """寫入報名資料"""
        db.collection('events').document(event_id)\
            .collection('participants').document(attendance.user_id)\
            .set(attendance.model_dump())

    def get_participant(self, event_id: str, user_id: str):
        doc = db.collection('events').document(event_id)\
            .collection('participants').document(user_id).get()
        return doc.to_dict() if doc.exists else None

    def get_event_statistics(self, event_id: str):
        """
        取得活動統計資料 (包含未回覆的計算)
        依照定案的優先順序邏輯處理
        """
        # 1. 取得所有「在籍」與「請假」的成員 (排除 INACTIVE)
        all_users_stream = db.collection('users')\
            .where('status', 'in', [UserStatus.ACTIVE, UserStatus.LEAVE])\
            .order_by('sort_order').stream()
        
        # 轉為 Dict 方便查詢，並保留排序
        users_map = {} # {uid: user_data}
        sorted_uids = []
        for u in all_users_stream:
            data = u.to_dict()
            users_map[data['line_id']] = data
            sorted_uids.append(data['line_id'])

        # 2. 取得該活動的所有報名紀錄
        participants_stream = db.collection('events').document(event_id)\
            .collection('participants').stream()
        
        attendance_map = {p.id: p.to_dict() for p in participants_stream}

        # 3. 分類容器
        stats = {
            "going": [],       # 確定出席
            "leave": [],       # 長期請假 (且未報名出席)
            "not_going": [],   # 不克出席
            "no_response": []  # 尚未回覆
        }

        # 4. 執行分類邏輯 (依照定案規則)
        for uid in sorted_uids:
            user = users_map[uid]
            att = attendance_map.get(uid) # 可能為 None
            
            # 顯示名稱邏輯：優先用社團暱稱
            display_name = user.get('club_name') or user.get('display_name')

            # 判斷變數
            u_status = user.get('status')
            e_status = att.get('status') if att else None

            # --- 邏輯開始 ---

            # Rule 1: 確定出席 (不管身分，只要報名 +1 就算)
            if e_status == ParticipantStatus.GOING:
                # 檢查是否有攜伴
                guests = att.get('guests', [])
                total_guests_adults = sum(g.get('adults', 1) for g in guests)
                total_guests_kids = sum(g.get('kids', 0) for g in guests)
                family_adults = att.get('family_adults', 0)
                family_kids = att.get('family_kids', 0)
                guest_count = len(guests)
                stats["going"].append({
                    "name": display_name,
                    "guests": guest_count,
                    "guest_details": guests
                })
            
            # Rule 2: 長期請假 (身分為 LEAVE 且 沒報名出席)
            # 注意：即使他在 Flex 按 -1，依然歸類在此，不算 "不克出席"
            elif u_status == UserStatus.LEAVE:
                stats["leave"].append({"name": display_name})

            # Rule 3: 不克出席 (身分 ACTIVE 且 報名 -1)
            elif u_status == UserStatus.ACTIVE and e_status == ParticipantStatus.NOT_GOING:
                stats["not_going"].append({"name": display_name})

            # Rule 4: 尚未回覆 (身分 ACTIVE 且 無紀錄)
            elif u_status == UserStatus.ACTIVE and e_status is None:
                stats["no_response"].append({"name": display_name})
            
            # Rule 5: 例外處理 (如身分 ACTIVE 但資料庫有奇怪的狀態)，歸入未回覆
            elif u_status == UserStatus.ACTIVE:
                stats["no_response"].append({"name": display_name})

        return stats

db_service = Database()