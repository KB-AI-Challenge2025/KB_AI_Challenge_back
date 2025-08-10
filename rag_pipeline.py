# rag_pipeline.py
import os, json
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from typing import Optional
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()
client = OpenAI()

PERSIST_DIR = "rag_store"
EMB_MODEL = "jhgan/ko-sroberta-multitask"

_SYSTEM = (
    "너는 한국어로 금융/생활 사기 대처 가이드를 만드는 조력자야. "
    "법률/투자 자문이 아님을 명시하고, 즉시 행동/향후 조치/재발 방지/신고 채널/출처를 "
    "JSON으로만 반환해."
)

_TEMPLATE = """[사용자 경험 요약]
{case_summary}

[카테고리]
{category}

[섹션]
{section}

[관련 근거 문서 발췌]
{context}

[출력 JSON 스키마]
{{
  "category": "{category}",
  "section": "{section}",
  "immediate_actions": ["..."],
  "next_steps": ["..."],
  "prevention_tips": ["..."],
  "where_to_report": [{{"name":"기관명","type":"전화/웹","value":"...", "note":"..."}}],
  "source_citations":[{{"title":"{category} 관련 자료","url":""}}],
  "disclaimer":"본 내용은 법률/투자 자문이 아닙니다. 긴급 상황은 112/금융회사 공식채널로 연락하세요."
}}
JSON만 출력하세요.
"""

class RAGEngine:
    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=PERSIST_DIR, settings=Settings(allow_reset=False)
        )
        self.coll = self.client.get_or_create_collection(
            "kb_advice_v1", metadata={"hnsw:space": "cosine"}
        )
        self.emb_model = SentenceTransformer(EMB_MODEL)

    def retrieve(self, query: str, category: str, top_k: int = 5, section: Optional[str] = None) -> str:
        q_emb = self.emb_model.encode(query).tolist()

        if section:
            where = {"$and": [
                {"category": category},
                {"section": section}
            ]}
        else:
            where = {"category": category}

        res = self.coll.query(
            query_embeddings=[q_emb],
            n_results=top_k,
            where=where,
        )
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]

        if not docs:
            return "- 관련 문서를 찾지 못했습니다."

        lines = []
        for d, m in zip(docs, metas):
            src = (m or {}).get("source", "")
            lines.append(f"- {d}\n(출처: {src})")
        return "\n\n".join(lines)

    def generate_json(self, case_summary: str, category: str, context: str, section: str) -> dict:
        prompt = _TEMPLATE.format(
            case_summary=case_summary, category=category, context=context, section=section
        )

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )

        text = (resp.choices[0].message.content or "").strip()

        # JSON 파싱 안전장치
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end+1]

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 최소 형태로라도 반환해 UI가 죽지 않게
            return {
                "category": category,
                "section": section,
                "immediate_actions": [],
                "next_steps": [],
                "prevention_tips": [],
                "where_to_report": [],
                "source_citations": [],
                "disclaimer": "본 내용은 법률/투자 자문이 아닙니다. 긴급 상황은 112/금융회사 공식채널로 연락하세요.",
                "_raw": text,  # 디버깅용
            }


rag_engine = RAGEngine()

