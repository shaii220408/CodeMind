from functools import lru_cache
from app.core.config import settings

@lru_cache(maxsize=1)
def model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(settings.embedding_model)

def embed_many(texts: list[str]) -> list[list[float]]:
    if not texts: return []
    return model().encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False).tolist()
