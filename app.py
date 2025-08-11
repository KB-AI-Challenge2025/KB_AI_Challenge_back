from flask import Flask, request, jsonify
import torch
import torch.nn.functional as F
from transformers import AutoModelForSequenceClassification, AutoTokenizer, AutoConfig
import joblib
from SQL_function import save_to_db, update_emotion_summary_all, save_full_log,get_user_dashboard,complete_mission
from model import predict_emotion
import pymysql
from datetime import datetime, date
from dotenv import load_dotenv
from rag_pipeline import rag_engine
import os
load_dotenv()
# ✅ Flask 앱 초기화
app = Flask(__name__)

# ✅ MySQL 연결
def get_connection():
    return pymysql.connect(
        host="127.0.0.1",
        user='root',
        password='0000',
        database='emotion_db',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

# ----------------------------------------------------------
# 발화에 따른 감정 누적
# ----------------------------------------------------------
@app.route("/predict", methods=["POST"])
def predict():
    data = request.get_json()
    user_text = data.get("user_text") or ""  # None이면 빈 문자열
    gpt_text = data.get("gpt_text")
    chat_id = data.get("chat_id")
    today = datetime.now().date()

    # user_text는 필수 아님
    if not all([gpt_text, chat_id]):
        return jsonify({"error": "chat_id, gpt_text 모두 필요합니다."}), 400

    # 단어 거르기
    NEUTRAL_KEYWORDS = {"고마워", "감사", "안녕", "ㅋㅋ", "ㅎㅎ", "웅", "응", "헉", "헐", "오", "와"}
    if any(word in user_text for word in NEUTRAL_KEYWORDS):
        save_full_log(chat_id, user_text, gpt_text, today)
        return jsonify({
            "message": "저장하지 않았습니다.",
            "result": {}
        })

    result = {}
    if user_text.strip():  # user_text 있을 때만 감정 분석
        result = predict_emotion(user_text)
        top_emotion = max(result, key=result.get)
        confidence = result[top_emotion]

        # 중립 50% 이상 필터링
        if "중립" in result and result["중립"] >= 50.0:
            save_to_db(user_text, top_emotion, confidence)
            save_full_log(chat_id, user_text, gpt_text, today)
            return jsonify({
                "message": "중립 감정이 50% 이상이라 저장하지 않았습니다.",
                "result": result
            })

        # 감정 저장
        save_to_db(user_text, top_emotion, confidence)
        update_emotion_summary_all(result)

    # 전체 대화 로그 저장 (감정 분석 여부와 관계없이)
    save_full_log(chat_id, user_text, gpt_text, today)

    return jsonify({
        "message": "감정 분석 완료 및 저장됨" if result else "user_text 없음, 전체 로그만 저장됨",
        "result": result
    })

# ----------------------------------------------------------
# 이벤트 저장 / 반환
# ----------------------------------------------------------
@app.route('/save_event', methods=['POST'])
def save_event():
    data = request.get_json()

    chat_id = int(data.get('chat_id'))
    event_text = data.get('event_text')
    event_type = data.get('event_type')

    if not all([chat_id, event_text, event_type]):
        return jsonify({'success': False, 'message': 'chat_id, event_text, event_type는 모두 필요합니다.'}), 400

    try:
        connection = get_connection()
        with connection.cursor() as cursor:
            query = """
                INSERT INTO events (chat_id, event_text, event_type)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    event_text = VALUES(event_text),
                    event_type = VALUES(event_type)
            """
            cursor.execute(query, (chat_id, event_text, event_type))
            connection.commit()

        return jsonify({'success': True, 'message': '이벤트가 저장(또는 업데이트)되었습니다.'}), 201

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/get_events/<int:chat_id>', methods=['GET'])
def get_events(chat_id):
    try:
        connection = pymysql.connect(
            host="127.0.0.1",
            user='root',
            password='0000',
            database='emotion_db',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

        with connection.cursor() as cursor:
            query = """
                SELECT event_text, event_type
                FROM events
                WHERE chat_id = %s
            """
            cursor.execute(query, (chat_id,))
            rows = cursor.fetchall()

        connection.close()

        return jsonify({
            'success': True,
            'chat_id': chat_id,
            'events': rows
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ----------------------------------------------------------
# 누적 감정 일별 / 월별 / 주별 제공
# ----------------------------------------------------------       

@app.route('/summary/daily/<date>', methods=['GET'])
def summary_daily(date):
    try:
        connection = get_connection()
        with connection.cursor() as cursor:
            query = """
                SELECT 
                    emotion,
                    ROUND(total_confidence / count, 2) AS avg_percent
                FROM emotion_summary
                WHERE date = %s
            """
            cursor.execute(query, (date,))
            rows = cursor.fetchall()

        if not rows:
            return jsonify({'success': False, 'message': f'{date}의 데이터가 없습니다.'}), 404

        return jsonify({'success': True, 'date': date, 'data': rows}), 200

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/summary/monthly/<month>', methods=['GET'])
def summary_monthly(month):
    try:
        connection = get_connection()
        with connection.cursor() as cursor:
            query = """
                SELECT 
                    emotion,
                    ROUND(SUM(total_confidence) / SUM(count), 2) AS avg_percent
                FROM emotion_summary
                WHERE DATE_FORMAT(date, '%%Y-%%m') = %s
                GROUP BY emotion
            """
            cursor.execute(query, (month,))
            rows = cursor.fetchall()

        if not rows:
            return jsonify({'success': False, 'message': f'{month}의 데이터가 없습니다.'}), 404

        return jsonify({'success': True, 'month': month, 'data': rows}), 200

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/summary/weekly/<start_date>/<end_date>', methods=['GET'])
def summary_weekly(start_date, end_date):
    if not start_date or not end_date:
        return jsonify({'success': False, 'message': '시작일과 종료일이 모두 필요합니다.'}), 400

    try:
        connection = get_connection()
        with connection.cursor() as cursor:
            query = """
                SELECT 
                    date,
                    emotion,
                    ROUND(total_confidence / count, 2) AS avg_percent
                FROM emotion_summary
                WHERE date BETWEEN %s AND %s
                ORDER BY date, emotion
            """
            cursor.execute(query, (start_date, end_date))
            rows = cursor.fetchall()

        if not rows:
            return jsonify({
                'success': False,
                'message': f'{start_date}부터 {end_date}까지의 데이터가 없습니다.'
            }), 404

        # ✅ 날짜 포맷 변환
        for row in rows:
            if isinstance(row['date'], (datetime, date)):
                row['date'] = row['date'].strftime('%Y-%m-%d')

        return jsonify({
            'success': True,
            'range': {
                'start_date': start_date,
                'end_date': end_date
            },
            'data': rows
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
# ----------------------------------------------------------
# 대화 내역 불러오기
# ----------------------------------------------------------     
@app.route("/get_conversations/<chat_id>", methods=["GET"])
def get_conversations(chat_id):
    try:
        connection = get_connection()
        with connection.cursor() as cursor:
            query = """
                SELECT date, user_text, gpt_text
                FROM conversation_log
                WHERE chat_id = %s
                ORDER BY date ASC, id ASC
            """
            cursor.execute(query, (chat_id,))
            rows = cursor.fetchall()
        connection.close()

        conversations = []
        for row in rows:
            conversations.append({
                "role": "user",
                "content": row["user_text"]
            })
            conversations.append({
                "role": "gpt",
                "content": row["gpt_text"]
            })

        return jsonify({
            "success": True,
            "conversations": conversations
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# ----------------------------------------------------------
# 최신 chat_id 가지고오기.
# ----------------------------------------------------------  
@app.route("/latest_chat_id", methods=["GET"])
def get_latest_chat_id():
    try:
        connection = get_connection()

        with connection.cursor() as cursor:
            query = """
                SELECT chat_id
                FROM events
                ORDER BY id DESC
                LIMIT 1
            """
            cursor.execute(query)
            row = cursor.fetchone()
        connection.close()

        if row:
            return jsonify({
                "success": True,
                "latest_chat_id": row["chat_id"]
            }), 200
        else:
            return jsonify({
                "success": False,
                "message": "이벤트 데이터가 없습니다."
            }), 404

    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500
# ----------------------------------------------------------
# 대시보드
# ----------------------------------------------------------
@app.route("/api/users/<int:user_id>/dashboard", methods=["GET"])
def dashboard(user_id):
    """
    대시보드 조회:
      - character: {user_id, total_exp, level, next_exp_req}
      - todayMission: {mission_id, title, is_completed}
    """
    character, today_mission = get_user_dashboard(user_id)
    return jsonify({
        "character": character,
        "todayMission": today_mission
    }), 200

# ----------------------------------------------------------
# 미션 완료
# ----------------------------------------------------------
@app.route("/api/users/<int:user_id>/missions/<int:mission_id>/complete", methods=["POST"])
def mission_complete(user_id, mission_id):
    """
    미션 완료 처리:
      - 이미 완료된 경우 409 에러
      - 완료 시 경험치 +1, 레벨업 감지 후 character 정보 반환
    """
    ok, updated_char = complete_mission(user_id, mission_id)
    if not ok:
        return jsonify({
            "error": "MissionAlreadyCompleted",
            "message": "이미 완료한 미션입니다!"
        }), 409

    return jsonify({
        "missionStatus": {
            "user_id": user_id,
            "mission_id": mission_id,
            "mission_date": date.today().isoformat(),
            "is_completed": True
        },
        "character": updated_char
    }), 200
    
# ----------------------------------------------------------
# rag
# ----------------------------------------------------------  

def load_section_items(category: str, section: str) -> list[str]:
    """rag_data/{category}_{section}.txt 를 라인 단위 체크 항목으로 변환"""
    path = os.path.join("rag_data", f"{category}_{section}.txt")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.strip("-·• ").strip() for ln in f.read().splitlines()]
    # 빈 줄 제거
    return [ln for ln in lines if ln]


@app.route("/advice/options", methods=["GET"])
def advice_options():
    category = request.args.get("category", "").strip()
    if not category:
        return jsonify({"success": False, "message": "category 쿼리 파라미터가 필요합니다."}), 400

    data = {
        "category": category,
        "sections": {
            "대처방안": load_section_items(category, "대처방안"),
        }
    }
    return jsonify({"success": True, "data": data}), 200

@app.route("/rag/advise", methods=["POST"])
def rag_advise():
    """
    입력 JSON:
    {
      "category": "보이스피싱",
      "user_text": "선택. 사용자가 서술한 경험",
      "chat_id": 123,   // 선택. 주어지면 events에서 event_text를 모아 요약으로 사용
      "section": "대처방안"  // 선택: 기본값 대처방안
    }
    """
    data = request.get_json() or {}
    category = (data.get("category") or "").strip()
    section  = (data.get("section") or "대처방안").strip()
    user_text = (data.get("user_text") or "").strip()
    chat_id   = data.get("chat_id")

    if not category:
        return jsonify({"success": False, "message": "category는 필수입니다."}), 400

    # case_summary 만들기
    case_summary = user_text
    if (not case_summary) and chat_id:
        try:
            connection = get_connection()
            with connection.cursor() as cursor:
                # 최근 것부터 모아 간단히 합침(원하면 limit/timestamp 조절)
                cursor.execute("""
                    SELECT event_text
                    FROM events
                    WHERE chat_id = %s
                    ORDER BY id DESC
                """, (chat_id,))
                rows = cursor.fetchall()
            connection.close()
            case_summary = " / ".join([r["event_text"] for r in rows if r.get("event_text")])[:2000]
        except Exception as e:
            return jsonify({"success": False, "message": f"이벤트 로딩 실패: {e}"}), 500

    if not case_summary:
        return jsonify({"success": False, "message": "user_text 또는 chat_id로부터 요약이 필요합니다."}), 400

    try:
        # 섹션 필터를 달고 검색 정밀도 ↑
        context = rag_engine.retrieve(query=case_summary, category=category, section=section, top_k=5)
        result  = rag_engine.generate_json(case_summary=case_summary, category=category, context=context, section=section)
        return jsonify({"success": True, "data": result}), 200
    except Exception as e:
        return jsonify({"success": False, "message": f"RAG 생성 실패: {e}"}), 500

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
