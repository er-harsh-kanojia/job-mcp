"""Skill demand across cached search results (no AI; pure counting)."""

from __future__ import annotations

import re
from collections import Counter

from ..scoring import STOPWORDS, tokens

# canonical skill -> display name
DISPLAY = {
    "python": "Python", "machine learning": "Machine Learning", "deep learning": "Deep Learning",
    "nlp": "NLP", "computer vision": "Computer Vision", "generative ai": "Generative AI",
    "llm": "LLMs", "rag": "RAG", "langchain": "LangChain", "llamaindex": "LlamaIndex",
    "langgraph": "LangGraph", "prompt engineering": "Prompt Engineering", "agents": "AI Agents",
    "fine-tuning": "Fine-tuning", "transformers": "Transformers", "hugging face": "Hugging Face",
    "pytorch": "PyTorch", "tensorflow": "TensorFlow", "keras": "Keras", "scikit-learn": "scikit-learn",
    "xgboost": "XGBoost", "pandas": "Pandas", "numpy": "NumPy", "opencv": "OpenCV",
    "vector databases": "Vector databases", "faiss": "FAISS", "pinecone": "Pinecone",
    "chromadb": "ChromaDB", "weaviate": "Weaviate", "milvus": "Milvus", "elasticsearch": "Elasticsearch",
    "mlops": "MLOps", "mlflow": "MLflow", "kubeflow": "Kubeflow", "airflow": "Airflow",
    "docker": "Docker", "kubernetes": "Kubernetes", "ci/cd": "CI/CD", "git": "Git",
    "aws": "AWS", "azure": "Azure", "gcp": "GCP", "sagemaker": "SageMaker", "azure openai": "Azure OpenAI",
    "vertex ai": "Vertex AI", "bedrock": "Bedrock", "databricks": "Databricks", "spark": "Spark",
    "sql": "SQL", "nosql": "NoSQL", "mongodb": "MongoDB", "postgresql": "PostgreSQL", "redis": "Redis",
    "fastapi": "FastAPI", "flask": "Flask", "django": "Django", "rest api": "REST APIs",
    "microservices": "Microservices", "java": "Java", "javascript": "JavaScript", "typescript": "TypeScript",
    "react": "React", "go": "Go", "c++": "C++", "statistics": "Statistics", "data science": "Data Science",
    "time series": "Time series", "recommendation systems": "Recommender systems",
    "reinforcement learning": "Reinforcement learning", "openai api": "OpenAI API",
    "llm evaluation": "LLM evaluation", "system design": "System design", "linux": "Linux",
    "power bi": "Power BI", "tableau": "Tableau", "kafka": "Kafka", "onnx": "ONNX", "triton": "Triton",
    "vllm": "vLLM", "cuda": "CUDA", "speech": "Speech / ASR", "ocr": "OCR", "yolo": "YOLO",
    "diffusion models": "Diffusion models", "graph neural networks": "GNNs", "snowflake": "Snowflake",
}

# alias (lowercase) -> canonical
ALIASES = {
    "ml": "machine learning", "machine-learning": "machine learning",
    "dl": "deep learning", "natural language processing": "nlp", "cv": "computer vision",
    "genai": "generative ai", "gen ai": "generative ai", "gen-ai": "generative ai",
    "llms": "llm", "large language models": "llm", "large language model": "llm",
    "retrieval augmented generation": "rag", "retrieval-augmented generation": "rag",
    "agentic ai": "agents", "ai agents": "agents", "autogen": "agents", "crewai": "agents",
    "fine tuning": "fine-tuning", "finetuning": "fine-tuning", "lora": "fine-tuning", "peft": "fine-tuning",
    "huggingface": "hugging face", "hf": "hugging face", "torch": "pytorch", "tf": "tensorflow",
    "sklearn": "scikit-learn", "scikit learn": "scikit-learn", "vector database": "vector databases",
    "vector db": "vector databases", "vector dbs": "vector databases", "vector store": "vector databases",
    "chroma": "chromadb", "ml ops": "mlops", "llmops": "mlops", "k8s": "kubernetes",
    "amazon web services": "aws", "microsoft azure": "azure", "google cloud": "gcp",
    "google cloud platform": "gcp", "aws sagemaker": "sagemaker", "pyspark": "spark",
    "apache spark": "spark", "postgres": "postgresql", "mysql": "sql", "rest": "rest api",
    "rest apis": "rest api", "restful": "rest api", "golang": "go", "js": "javascript",
    "ci cd": "ci/cd", "cicd": "ci/cd", "github actions": "ci/cd", "openai": "openai api",
    "gpt": "openai api", "evals": "llm evaluation", "llm evals": "llm evaluation",
    "recommender systems": "recommendation systems", "asr": "speech", "speech recognition": "speech",
    "stable diffusion": "diffusion models", "gnn": "graph neural networks", "prompting": "prompt engineering",
    "transformer": "transformers", "bert": "transformers", "llama index": "llamaindex",
    "elastic search": "elasticsearch", "power-bi": "power bi",
}

# Terms that are only matched in descriptions as whole words (short / ambiguous ones excluded).
_DESC_SKIP = {"go", "git", "rest", "ml", "dl", "cv", "tf", "hf", "js", "gpt", "sql", "rest api", "speech",
              "statistics", "agents", "linux", "transformer", "transformers"}


def normalize_skill(raw: str) -> str:
    s = re.sub(r"\s+", " ", (raw or "").strip().lower())
    s = s.strip(" .;:-•*()[]")
    return ALIASES.get(s, s)


def display(skill: str) -> str:
    return DISPLAY.get(skill, skill.title() if skill.islower() and len(skill) > 3 else skill.upper()
                       if len(skill) <= 3 else skill)


def _vocab_patterns() -> list[tuple[str, re.Pattern]]:
    terms = {k: k for k in DISPLAY}
    terms.update(ALIASES)
    pats = []
    for term, canon in sorted(terms.items(), key=lambda kv: -len(kv[0])):
        if term in _DESC_SKIP:
            continue
        pats.append((canon, re.compile(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])")))
    return pats


_PATTERNS: list[tuple[str, re.Pattern]] | None = None


def job_skills(job: dict) -> set[str]:
    """Canonical skills of one job: its skills list + known terms in title/description."""
    global _PATTERNS
    if _PATTERNS is None:
        _PATTERNS = _vocab_patterns()
    found = set()
    for s in job.get("skills") or []:
        n = normalize_skill(str(s))
        if 1 < len(n) <= 40:
            found.add(n)
    text = f" {job.get('title') or ''} {job.get('description') or ''} ".lower()
    for canon, pat in _PATTERNS:
        if pat.search(text):
            found.add(canon)
    return found


def role_tokens(role: str) -> set[str]:
    return tokens(role)


def job_matches_role(job: dict, role_toks: set[str]) -> bool:
    if not role_toks:
        return True
    title_toks = tokens(job.get("title") or "")
    if role_toks & title_toks:
        return True
    # "GenAI Engineer" should also match "LLM Engineer" / "Generative AI ..." titles
    related = {"genai": {"llm", "genai"}, "llm": {"llm", "genai"}, "ml": {"ml", "ai", "dl"},
               "ai": {"ai", "ml", "genai", "llm"}, "nlp": {"nlp", "llm"}, "cv": {"cv"},
               "mlops": {"mlops"}, "datascience": {"datascience", "ml"}}
    for t in role_toks:
        if related.get(t, set()) & title_toks:
            return True
    return False


def skill_demand(jobs: list[dict], role: str, top: int = 15) -> dict:
    """{"matched_jobs": n, "rows": [{"skill", "key", "jobs"}]} for jobs matching ``role``."""
    rt = role_tokens(role)
    matched = [j for j in jobs if job_matches_role(j, rt)]
    counts: Counter[str] = Counter()
    for j in matched:
        counts.update(job_skills(j))
    # drop the role words themselves (e.g. "engineer") and very generic terms
    for t in list(counts):
        if t in STOPWORDS or t in {"ai", "artificial intelligence", "communication", "team player"}:
            del counts[t]
    min_jobs = 2 if len(matched) >= 10 else 1
    rows = [{"skill": display(k), "key": k, "jobs": n}
            for k, n in counts.most_common() if n >= min_jobs][:top]
    return {"matched_jobs": len(matched), "rows": rows}
