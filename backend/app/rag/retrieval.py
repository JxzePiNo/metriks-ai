from collections import defaultdict
from threading import Lock


def rrf(rankings: list[list[dict]], k: int = 60) -> list[dict]:
    scores: dict[str, float] = defaultdict(float)
    documents = {}
    for ranking in rankings:
        seen = set()
        for rank, hit in enumerate(ranking, 1):
            key = hit["_id"]
            if key in seen:
                continue
            seen.add(key)
            documents[key] = hit
            scores[key] += 1 / (k + rank)
    return [
        {**documents[key], "rrf_score": score}
        for key, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    ]


class Search:
    def __init__(self, settings):
        from elasticsearch import Elasticsearch
        from sentence_transformers import CrossEncoder, SentenceTransformer

        self.settings = settings
        self.index = settings.elasticsearch_index
        self.client = Elasticsearch(
            settings.elasticsearch_url,
            api_key=settings.elasticsearch_api_key.get_secret_value() or None,
            request_timeout=60,
        )
        self.encoder = SentenceTransformer(settings.embedding_model, device="cpu")
        self.reranker = CrossEncoder(settings.reranker_model, device="cpu")
        self.lock = Lock()
        dims = self.encoder.get_sentence_embedding_dimension()
        if not self.client.indices.exists(index=self.index):
            self.client.indices.create(
                index=self.index,
                mappings={
                    "dynamic": "strict",
                    "_meta": {
                        "embedding_model": settings.embedding_model,
                        "retrieval_schema": "en-it-v2",
                    },
                    "properties": {
                        "text": {
                            "type": "text",
                            "fields": {
                                "en": {"type": "text", "analyzer": "english"},
                                "it": {"type": "text", "analyzer": "italian"},
                            },
                        },
                        "vector": {
                            "type": "dense_vector",
                            "dims": dims,
                            "index": True,
                            "similarity": "cosine",
                        },
                        **{
                            key: {"type": "keyword"}
                            for key in [
                                "tenant_id",
                                "document_id",
                                "allowed_users",
                                "classification",
                                "confidentiality",
                                "title",
                                "language",
                            ]
                        },
                        "page": {"type": "integer"},
                    },
                },
            )
        else:
            mapping = self.client.indices.get_mapping(index=self.index)
            for value in mapping.values():
                if value["mappings"]["properties"]["vector"]["dims"] != dims:
                    raise ValueError("Embedding dimension mismatch; use a new index")
                if (
                    value["mappings"].get("_meta", {}).get("embedding_model")
                    != settings.embedding_model
                ):
                    raise ValueError("Embedding model mismatch; use a new index")
                if (
                    value["mappings"].get("_meta", {}).get("retrieval_schema")
                    != "en-it-v2"
                ):
                    raise ValueError("Multilingual mapping required; use a new index")

    def index_chunks(self, chunks: list[dict]):
        from elasticsearch.helpers import bulk

        with self.lock:
            vectors = self.encoder.encode(
                [c["text"] for c in chunks],
                normalize_embeddings=True,
                show_progress_bar=False,
            ).tolist()
        bulk(
            self.client,
            [
                {
                    "_index": self.index,
                    "_id": c["id"],
                    "_source": {
                        **{k: v for k, v in c.items() if k != "id"},
                        "vector": vector,
                    },
                }
                for c, vector in zip(chunks, vectors, strict=True)
            ],
            refresh="wait_for",
        )

    def delete(self, tenant: str, document_id: str):
        self.client.delete_by_query(
            index=self.index,
            query={
                "bool": {
                    "filter": [
                        {"term": {"tenant_id": tenant}},
                        {"term": {"document_id": document_id}},
                    ]
                }
            },
            refresh=True,
        )

    def retrieve(
        self, question: str, p, document_ids: list[str], labels: list[str], top_k: int
    ) -> list[dict]:
        if not document_ids:
            return []
        filters = [
            {"term": {"tenant_id": p.tenant_id}},
            {"term": {"allowed_users": p.user_id}},
            {"terms": {"document_id": document_ids}},
        ]
        if labels:
            filters.append({"terms": {"classification": labels}})
        with self.lock:
            vector = self.encoder.encode(question, normalize_embeddings=True).tolist()
        sparse = self.client.search(
            index=self.index,
            size=30,
            source_excludes=["vector"],
            query={
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": question,
                                "fields": ["text", "text.en", "text.it"],
                                "type": "best_fields",
                            }
                        }
                    ],
                    "filter": filters,
                }
            },
        )
        dense = self.client.search(
            index=self.index,
            size=30,
            source_excludes=["vector"],
            knn={
                "field": "vector",
                "query_vector": vector,
                "k": 30,
                "num_candidates": 100,
                "filter": {"bool": {"filter": filters}},
            },
        )
        fused = rrf([sparse["hits"]["hits"], dense["hits"]["hits"]])[:40]
        if not fused:
            return []
        with self.lock:
            scores = self.reranker.predict(
                [(question, h["_source"]["text"]) for h in fused]
            )
        for hit, score in zip(fused, scores, strict=True):
            hit["rerank_score"] = float(score)
        return sorted(fused, key=lambda h: h["rerank_score"], reverse=True)[:top_k]
