from flask import Flask, request, jsonify
import torch
import torch.nn.functional as F
from transformers import AutoModelForSequenceClassification, AutoTokenizer, AutoConfig
import joblib
from SQL_function import save_to_db, update_emotion_summary_all
from model import predict_emotion
import pymysql
from datetime import datetime, date
# ✅ Flask 앱 초기화
app = Flask(__name__)

        # ✅ MySQL 연결
connection = pymysql.connect(
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
    sentence = data.get("text")

    if not sentence:
        return jsonify({"error": "No sentence provided"}), 400

    result = predict_emotion(sentence)  # ➜ {'불안': 12.4, '기쁨': 31.2, ...}
    top_emotion = max(result, key=result.get)
    confidence = result[top_emotion]

    # ✅ 중립 50% 이상 필터링
    if "중립" in result and result["중립"] >= 50.0:
        save_to_db(sentence, top_emotion, confidence)
        return jsonify({
            "message": "중립 감정이 50% 이상이라 저장하지 않았습니다.",
            "result": result
        })

    # ✅ 문장 저장 (top 감정 기준)
    save_to_db(sentence, top_emotion, confidence)

    # ✅ 전체 감정 누적 저장
    update_emotion_summary_all(result)

    return jsonify({
        "message": "감정 분석 완료 및 저장됨",
        "result": result
    })
# ----------------------------------------------------------
# 이벤트 저장 / 반환
# ----------------------------------------------------------
@app.route('/save_event', methods=['POST'])
def save_event():
    data = request.get_json()

    chat_id = data.get('chat_id')
    event_text = data.get('event_text')
    event_type = data.get('event_type')

    if not all([chat_id, event_text, event_type]):
        return jsonify({'success': False, 'message': 'chat_id, event_text, event_type는 모두 필요합니다.'}), 400

    try:
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


    

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
