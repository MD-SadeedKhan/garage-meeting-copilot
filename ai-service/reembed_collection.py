"""Copy a Qdrant collection into a new one, re-embedding each point's `text`
(transcripts) or `content` (summaries) with the configured embedding model.
Same point ids, same payload; only the vectors change. The source is never
written, and re-running upserts by id.

Run inside the ai-service container, with the NEW model set for this process
only (live traffic keeps whatever the service's own settings say):

    docker exec -e EMBEDDING_BASE_URL=https://earngpt.nodes.deploymachine.com/v1 \
      -e OPENAI_EMBEDDING_MODEL=qwen3-embedding-0.6b -e QDRANT_VECTOR_SIZE=1024 \
      copilot-ai-service python reembed_collection.py meeting_transcripts meeting_transcripts_qe1024
"""
from __future__ import annotations

import asyncio
import sys

from qdrant_client.http import models as qm

from app.services.memory.qdrant_retriever import QdrantRetriever

PAGE = 64


async def main(src: str, dst: str) -> None:
    r = QdrantRetriever()
    q = await r._get_client()
    dim = r._settings.qdrant_vector_size
    names = [c.name for c in (await q.get_collections()).collections]
    if dst not in names:
        await q.create_collection(
            collection_name=dst,
            vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE, on_disk=True),
        )
        for field, schema in ((await q.get_collection(src)).payload_schema or {}).items():
            await q.create_payload_index(dst, field_name=field, field_schema=schema.data_type)
    total = (await q.get_collection(src)).points_count
    print(f"[reembed] {src} ({total}) -> {dst} with {r._settings.openai_embedding_model} {dim}-d", flush=True)

    offset, done, skipped = None, 0, 0
    while True:
        points, offset = await q.scroll(src, limit=PAGE, offset=offset, with_payload=True, with_vectors=False)
        keep = [p for p in points if ((p.payload or {}).get("text") or (p.payload or {}).get("content") or "").strip()]
        skipped += len(points) - len(keep)
        if keep:
            texts = [(p.payload.get("text") or p.payload.get("content")) for p in keep]
            vectors = await r.embed_texts(texts)
            if any(len(v) != dim for v in vectors):
                raise SystemExit(f"model returned {len(vectors[0])} dims, expected {dim}")
            await q.upsert(dst, points=[qm.PointStruct(id=p.id, vector=v, payload=p.payload) for p, v in zip(keep, vectors)])
        done += len(keep)
        print(f"[reembed] {done} copied, {skipped} skipped (no text)", flush=True)
        if offset is None:
            break
    print(f"[reembed] finished: {dst} has {(await q.get_collection(dst)).points_count} points (source {total})", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] == sys.argv[2]:
        sys.exit("usage: reembed_collection.py <from> <to>")
    asyncio.run(main(sys.argv[1], sys.argv[2]))
