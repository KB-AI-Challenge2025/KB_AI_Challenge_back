import torch
import torch.nn.functional as F
import joblib
from transformers import AutoModelForSequenceClassification, AutoTokenizer, AutoConfig
# ✅ 감정 예측 함수
# ✅ 모델 경로 및 디바이스
from transformers import ElectraConfig, ElectraTokenizer, ElectraForSequenceClassification
import torch
import joblib

# 경로
MODEL_PATH = "./model"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# KoElectra 기반 구성
config = ElectraConfig.from_pretrained(MODEL_PATH, local_files_only=True)
tokenizer = ElectraTokenizer.from_pretrained(MODEL_PATH, local_files_only=True)
model = ElectraForSequenceClassification.from_pretrained(
    MODEL_PATH,
    config=config,
    local_files_only=True
).to(DEVICE)

# 라벨 인코더
label_encoder = joblib.load(f"{MODEL_PATH}/KoELECTRA.pkl")
label_names = label_encoder.classes_



def predict_emotion(text):
    model.eval()
    inputs = tokenizer(text, return_tensors="pt", truncation=True, padding="max_length", max_length=128).to(DEVICE)
    with torch.no_grad():
        outputs = model(**inputs)
        probs = F.softmax(outputs.logits, dim=1).squeeze().cpu().numpy()
    return {label: round(prob * 100, 2) for label, prob in zip(label_names, probs)}