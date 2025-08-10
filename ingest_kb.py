# ingest_kb.py
import os, glob, uuid, hashlib
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

EMB_MODEL = "jhgan/ko-sroberta-multitask"  # 가볍고 한국어 OK
CHUNK_SIZE, OVERLAP = 600, 120
PERSIST_DIR = "rag_store"

def chunk_text(t, size=CHUNK_SIZE, overlap=OVERLAP):
    out, i = [], 0
    while i < len(t):
        out.append(t[i:i+size])
        i += max(1, size - overlap)
    return out

def category_from_filename(path: str) -> str:
    """rag_data/보이스피싱_대처방안.txt -> 보이스피싱"""
    name = os.path.basename(path)
    stem, _ = os.path.splitext(name)
    parts = stem.split("_")
    return parts[0].strip() if parts else ""

def section_from_filename(path: str) -> str:
    """rag_data/보이스피싱_대처방안.txt -> 대처방안 (없으면 '기타')"""
    name = os.path.basename(path)
    stem, _ = os.path.splitext(name)
    parts = stem.split("_")
    return parts[1].strip() if len(parts) >= 2 else "기타"

def stable_id(source: str, chunk_index: int, text: str) -> str:
    """재인제스트 시 중복 방지를 위한 안정적 ID (파일명+인덱스+내용 해시)"""
    h = hashlib.sha1(f"{source}::{chunk_index}::{text}".encode("utf-8")).hexdigest()
    return f"{h}"

def main():
    os.makedirs(PERSIST_DIR, exist_ok=True)
    client = chromadb.PersistentClient(
        path=PERSIST_DIR,
        settings=Settings(allow_reset=True)
    )
    coll = client.get_or_create_collection(
        "kb_advice_v1",
        metadata={"hnsw:space":"cosine"}
    )

    model = SentenceTransformer(EMB_MODEL)

    for fp in glob.glob("rag_data/*.txt"):
        category = category_from_filename(fp)
        section  = section_from_filename(fp)
        if not category:
            print(f"⚠️  카테고리를 알 수 없어 건너뜀: {fp}")
            continue

        with open(fp, "r", encoding="utf-8") as f:
            full = f.read().strip()
        if not full:
            print(f"⚠️  빈 파일 건너뜀: {fp}")
            continue

        chunks = chunk_text(full)

        # 배치 임베딩으로 속도 향상
        embs = model.encode(chunks, batch_size=16, show_progress_bar=True)
        for idx, (ch, emb) in enumerate(zip(chunks, embs)):
            source = os.path.basename(fp)
            uid = stable_id(source, idx, ch)  # <- uuid 대신 안정적 ID
            coll.add(
                documents=[ch],
                embeddings=[emb.tolist() if hasattr(emb, "tolist") else list(emb)],
                metadatas=[{
                    "category": category,     # 필수: RAG where 필터
                    "section":  section,      # ★ 추가: 섹션 필터 (대처방안/신고처/예방팁 등)
                    "source":   source,
                    "chunk_index": idx
                }],
                ids=[uid]
            )

    print("✅ Ingest finished.")

if __name__ == "__main__":
    main()