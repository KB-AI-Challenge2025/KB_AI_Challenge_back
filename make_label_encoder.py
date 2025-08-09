import os
from sklearn.preprocessing import LabelEncoder
import joblib

# 감정 클래스 리스트 (예시)
classes = ["기쁨", "슬픔", "분노", "불안", "중립", "놀람"]

# 프로젝트 내 model 폴더 경로
model_dir = "model"
os.makedirs(model_dir, exist_ok=True)

# LabelEncoder 생성 및 학습
le = LabelEncoder()
le.fit(classes)

# pkl 파일로 저장
pkl_path = os.path.join(model_dir, "KoELECTRA.pkl")
joblib.dump(le, pkl_path)

print("Saved PKL file at:", pkl_path)
