# ✅ MySQL 저장 함수
import pymysql
from datetime import datetime
import pymysql.cursors

MYSQL_CONFIG = {
    "host": "127.0.0.1",        # 또는 "localhost"
    "user": "root",
    "password": "0000",   # ✅ 여기 본인 비밀번호 입력
    "database": "emotion_db",   # ✅ 사전에 생성한 DB 이름
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

def save_full_log(chat_id, user_text, gpt_text, date):
    connection = pymysql.connect(**MYSQL_CONFIG)
    with connection.cursor() as cursor:
        query = """
            INSERT INTO conversation_log (chat_id, date, user_text, gpt_text)
            VALUES (%s, %s, %s, %s)
        """
        cursor.execute(query, (chat_id, date, user_text, gpt_text))
        connection.commit()

def save_to_db(sentence, emotion, confidence):
    conn = pymysql.connect(**MYSQL_CONFIG)
    with conn.cursor() as cursor:
        sql = "INSERT INTO emotion_logs (sentence, top_emotion, confidence) VALUES (%s, %s, %s)"
        cursor.execute(sql, (sentence, emotion, confidence))
    conn.commit()
    conn.close()



def update_emotion_summary_all(prob_dict):
    conn = pymysql.connect(**MYSQL_CONFIG)
    today = datetime.now().date()

    with conn.cursor() as cursor:
        for emotion, confidence in prob_dict.items():
            # 감정 존재 여부 확인
            cursor.execute("SELECT count FROM emotion_summary WHERE date=%s AND emotion=%s", (today, emotion))
            row = cursor.fetchone()

            if row:
                cursor.execute("""
                    UPDATE emotion_summary
                    SET total_confidence = total_confidence + %s,
                        count = count + 1
                    WHERE date = %s AND emotion = %s
                """, (confidence, today, emotion))
            else:
                cursor.execute("""
                    INSERT INTO emotion_summary (date, emotion, total_confidence, count)
                    VALUES (%s, %s, %s, 1)
                """, (today, emotion, confidence))

    conn.commit()
    conn.close()

def day_summarize():
    conn = pymysql.connect(**MYSQL_CONFIG)
    today = datetime.now().date()

# 대쉬보드 (오늘의 미션, 캐릭터 정보)
def get_user_dashboard(user_id: int):
    today = datetime.now().date()
    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        with conn.cursor() as cur:
            # 1) 캐릭터 정보 조회 + 없으면 생성
            cur.execute("""
                SELECT user_id, total_exp, level, next_exp_req
                  FROM UserCharacter
                 WHERE user_id=%s
            """, (user_id,))
            character = cur.fetchone()

            if not character:
                # 기본 캐릭터 생성 (XP=0, LV=1, next_req=5)
                cur.execute("""
                    INSERT INTO UserCharacter (user_id, total_exp, level, next_exp_req)
                    VALUES (%s, %s, %s, %s)
                """, (user_id, 0, 1, 5))
                character = {
                    "user_id": user_id,
                    "total_exp": 0,
                    "level": 1,
                    "next_exp_req": 5,
                }

            # 2) 오늘 완료 처리된 미션이 있는지 먼저 체크
            cur.execute("""
                SELECT ums.mission_id, dm.title
                  FROM UserMissionStatus ums
             LEFT JOIN DailyMission dm
                    ON dm.mission_id = ums.mission_id
                 WHERE ums.user_id=%s
                   AND ums.mission_date=%s
                   AND ums.is_completed=TRUE
            """, (user_id, today))
            done = cur.fetchone()

            if done:
                today_mission = {
                    "mission_id": done["mission_id"],
                    "title": done["title"],
                    "is_completed": True
                }
            else:
                # 3) 오늘 완료되지 않은 미션 중에서 랜덤으로 하나 선택
                cur.execute("""
                    SELECT dm.mission_id, dm.title
                      FROM DailyMission dm
                 LEFT JOIN UserMissionStatus ums
                        ON ums.mission_id = dm.mission_id
                       AND ums.user_id = %s
                       AND ums.mission_date = %s
                     WHERE ums.mission_id IS NULL
                    ORDER BY RAND()
                    LIMIT 1
                """, (user_id, today))
                row = cur.fetchone()
                if row:
                    today_mission = {
                        "mission_id": row["mission_id"],
                        "title": row["title"],
                        "is_completed": False
                    }
                else:
                    today_mission = None

        # 캐릭터 최초 생성 시 INSERT 반영
        conn.commit()
        return character, today_mission

    finally:
        conn.close()


# 미션 완료
def complete_mission(user_id: int, mission_id: int):
    today = datetime.now().date()
    conn = pymysql.connect(**MYSQL_CONFIG)
    try:
        with conn.cursor() as cur:
            # 날짜 기준으로 오늘 완료 여부 확인
            cur.execute("""
                SELECT mission_id, is_completed
                  FROM UserMissionStatus
                 WHERE user_id=%s AND mission_date=%s
                 LIMIT 1
            """, (user_id, today))
            row = cur.fetchone()

            if row and row["is_completed"]:
                return False, None  # 이미 오늘 완료

            if row:
                cur.execute("""
                    UPDATE UserMissionStatus
                       SET mission_id=%s, is_completed=TRUE
                     WHERE user_id=%s AND mission_date=%s
                """, (mission_id, user_id, today))
            else:
                cur.execute("""
                    INSERT INTO UserMissionStatus (user_id, mission_id, mission_date, is_completed)
                    VALUES (%s, %s, %s, TRUE)
                """, (user_id, mission_id, today))

            # XP 보상 (레벨업 한 번만)
            xp_reward = 1
            cur.execute("""
                SELECT total_exp, level, next_exp_req
                  FROM UserCharacter
                 WHERE user_id=%s
                 LIMIT 1
            """, (user_id,))
            char = cur.fetchone()
            if not char:
                total_exp = xp_reward
                level, next_req = 1, 5
                cur.execute("""
                    INSERT INTO UserCharacter (user_id, total_exp, level, next_exp_req)
                    VALUES (%s, %s, %s, %s)
                """, (user_id, total_exp, level, next_req))
            else:
                total_exp = char["total_exp"] + xp_reward
                level, next_req = char["level"], char["next_exp_req"]
                if total_exp >= next_req:
                    total_exp -= next_req
                    level += 1
                    next_req = int(next_req * 1.2)
                cur.execute("""
                    UPDATE UserCharacter
                       SET total_exp=%s, level=%s, next_exp_req=%s
                     WHERE user_id=%s
                """, (total_exp, level, next_req, user_id))

        conn.commit()
        return True, {
            "user_id": user_id,
            "total_exp": total_exp,
            "level": level,
            "next_exp_req": next_req
        }
    finally:
        conn.close()