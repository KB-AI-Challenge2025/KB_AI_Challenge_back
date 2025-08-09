# ✅ MySQL 저장 함수
import pymysql
from datetime import datetime

MYSQL_CONFIG = {
    "host": "127.0.0.1",        # 또는 "localhost"
    "user": "root",
    "password": "0000",   # ✅ 여기 본인 비밀번호 입력
    "database": "emotion_db",   # ✅ 사전에 생성한 DB 이름
    "charset": "utf8mb4"
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