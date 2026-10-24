from app.core.config import settings

def answer(question: str, evidence: list[dict]) -> str:
    if not settings.llm_api_key:
        if not evidence: return "I could not find sufficient repository evidence to answer this question."
        lines=[f"Based on the indexed repository evidence, the most relevant location is {evidence[0]['file']} ({evidence[0]['start_line']}-{evidence[0]['end_line']})."]
        lines.append(f"The relevant symbol is {evidence[0]['symbol']}. The retrieved code begins:\n\n{evidence[0]['content'][:1800]}")
        lines.append("\nLLM fallback mode is active because LLM_API_KEY is not configured.")
        return "\n".join(lines)
    from openai import OpenAI
    client=OpenAI(api_key=settings.llm_api_key,base_url=settings.llm_base_url)
    context="\n\n".join(f"SOURCE: {e['file']}:{e['start_line']}-{e['end_line']} ({e['symbol']})\n{e['content']}" for e in evidence)
    prompt=f"""You are CodeRAG, a codebase assistant. Answer ONLY from the repository evidence below. Never invent files, symbols, behavior, or configuration. Distinguish observation from inference. If evidence is insufficient, say so. Cite important claims as file:line-line.\n\nQUESTION:\n{question}\n\nEVIDENCE:\n{context}"""
    r=client.chat.completions.create(model=settings.llm_model,messages=[{"role":"system","content":"You are a strict source-grounded software repository assistant."},{"role":"user","content":prompt}],temperature=0)
    return r.choices[0].message.content or "No grounded answer generated."
