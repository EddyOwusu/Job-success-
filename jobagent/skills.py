"""Tech skill taxonomy, aliases, and skill extraction from job adverts."""
from __future__ import annotations

import re
from functools import lru_cache

# canonical name -> aliases (lowercase). Canonical names are what we show.
TAXONOMY: dict[str, list[str]] = {
    # languages
    "Python": ["python", "python3"],
    "Java": ["java"],
    "JavaScript": ["javascript", "js", "ecmascript", "es6"],
    "TypeScript": ["typescript", "ts"],
    "Go": ["golang", "go lang", r"\bgo\b(?= ?(?:,|/|and|or|\)|developer|engineer|services))"],
    "Rust": ["rust"],
    "C#": ["c#", "csharp", "c sharp"],
    "C++": ["c++", "cpp"],
    "C": [r"\bc\b(?= ?(?:/c\+\+|,|programming))"],
    "Kotlin": ["kotlin"],
    "Scala": ["scala"],
    "Ruby": ["ruby"],
    "PHP": ["php"],
    "Swift": ["swift"],
    "R": [r"\br\b(?= ?(?:,|/|and|or|programming|studio))"],
    "Elixir": ["elixir"],
    "SQL": ["sql"],
    "Bash": ["bash", "shell scripting"],
    # backend frameworks
    "Django": ["django"],
    "Flask": ["flask"],
    "FastAPI": ["fastapi", "fast api"],
    "Spring": ["spring boot", "spring framework", "springboot"],
    ".NET": [".net", "dotnet", "asp.net"],
    "Node.js": ["node.js", "nodejs", "node"],
    "Express": ["express.js", "expressjs"],
    "Ruby on Rails": ["rails", "ruby on rails"],
    "Laravel": ["laravel"],
    "GraphQL": ["graphql"],
    "gRPC": ["grpc"],
    "REST APIs": ["restful", "rest api", "rest apis", "apis"],
    "Microservices": ["microservices", "microservice", "service-oriented"],
    # frontend
    "React": ["react", "react.js", "reactjs"],
    "Next.js": ["next.js", "nextjs"],
    "Vue": ["vue", "vue.js", "vuejs"],
    "Angular": ["angular"],
    "Svelte": ["svelte"],
    "HTML": ["html", "html5"],
    "CSS": ["css", "css3", "sass", "scss", "tailwind"],
    "Redux": ["redux"],
    "React Native": ["react native"],
    "Flutter": ["flutter"],
    "iOS": ["ios"],
    "Android": ["android"],
    # data
    "PostgreSQL": ["postgresql", "postgres"],
    "MySQL": ["mysql", "mariadb"],
    "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"],
    "Elasticsearch": ["elasticsearch", "opensearch"],
    "DynamoDB": ["dynamodb"],
    "Cassandra": ["cassandra"],
    "Kafka": ["kafka"],
    "RabbitMQ": ["rabbitmq"],
    "Spark": ["spark", "pyspark"],
    "Airflow": ["airflow"],
    "dbt": ["dbt"],
    "Snowflake": ["snowflake"],
    "BigQuery": ["bigquery", "big query"],
    "Databricks": ["databricks"],
    "Pandas": ["pandas"],
    "NumPy": ["numpy"],
    "ETL": ["etl", "elt", "data pipelines", "data pipeline"],
    "Data Warehousing": ["data warehouse", "data warehousing"],
    # ML / AI
    "Machine Learning": ["machine learning", "ml"],
    "Deep Learning": ["deep learning"],
    "PyTorch": ["pytorch"],
    "TensorFlow": ["tensorflow"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "LLMs": ["llm", "llms", "large language models", "generative ai", "genai"],
    "NLP": ["nlp", "natural language processing"],
    "Computer Vision": ["computer vision"],
    "MLOps": ["mlops"],
    # cloud / infra
    "AWS": ["aws", "amazon web services"],
    "GCP": ["gcp", "google cloud"],
    "Azure": ["azure"],
    "Docker": ["docker", "containers", "containerisation", "containerization"],
    "Kubernetes": ["kubernetes", "k8s", "eks", "gke", "aks"],
    "Terraform": ["terraform"],
    "Ansible": ["ansible"],
    "Helm": ["helm"],
    "CI/CD": ["ci/cd", "ci / cd", "continuous integration", "continuous delivery", "continuous deployment"],
    "GitHub Actions": ["github actions"],
    "Jenkins": ["jenkins"],
    "GitLab CI": ["gitlab ci"],
    "Linux": ["linux", "unix"],
    "Serverless": ["serverless", "lambda"],
    "Observability": ["observability", "prometheus", "grafana", "datadog", "opentelemetry"],
    "Git": ["git"],
    # practices
    "Testing": ["unit testing", "tdd", "test-driven", "pytest", "jest", "automated testing", "integration tests"],
    "Agile": ["agile", "scrum", "kanban"],
    "System Design": ["system design", "distributed systems", "scalable systems"],
    "Security": ["application security", "appsec", "owasp", "secure coding"],
    "Payments": ["payments", "payment systems"],
}

# Short names that are also English words; only their explicit patterns are used
AMBIGUOUS = {"Go", "R", "C"}

NICE_TO_HAVE_HEADERS = re.compile(
    r"(nice to have|nice-to-have|bonus|desirable|preferred|would be a plus|a plus|great if|"
    r"extra credit|not required|ideally)", re.I
)
REQUIRED_HEADERS = re.compile(
    r"(requirements|what you('|’)ll need|what we('|’)re looking for|you have|you will have|must have|"
    r"essential|about you|qualifications|skills and experience|who you are)", re.I
)


@lru_cache(maxsize=1)
def _compiled() -> list[tuple[str, re.Pattern]]:
    out = []
    for canon, aliases in TAXONOMY.items():
        parts = []
        extra = [] if canon in AMBIGUOUS else [canon.lower()]
        for a in aliases + extra:
            if a.startswith("\\b") or "(?=" in a:
                parts.append(a)
            else:
                parts.append(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9+#])")
        out.append((canon, re.compile("|".join(parts), re.I)))
    return out


def canonical(skill: str) -> str:
    """Map a free-text skill name to its canonical taxonomy name (or itself)."""
    s = skill.strip().lower()
    for canon, aliases in TAXONOMY.items():
        if s == canon.lower() or s in aliases:
            return canon
    return skill.strip()


def extract_skills(text: str) -> set[str]:
    text = text or ""
    return {canon for canon, pat in _compiled() if pat.search(text)}


def extract_weighted(text: str) -> dict[str, float]:
    """Skills in the advert with a weight: 1.0 required, 0.4 nice-to-have, 0.7 unknown section."""
    weights: dict[str, float] = {}
    section_weight = 0.7
    for line in (text or "").splitlines():
        stripped = line.strip()
        is_header = len(stripped) < 80 and not stripped.startswith("-")
        if is_header and NICE_TO_HAVE_HEADERS.search(stripped):
            section_weight = 0.4
        elif is_header and REQUIRED_HEADERS.search(stripped):
            section_weight = 1.0
        line_weight = 0.4 if NICE_TO_HAVE_HEADERS.search(stripped) else section_weight
        for skill in extract_skills(stripped):
            weights[skill] = max(weights.get(skill, 0), line_weight)
    return weights
