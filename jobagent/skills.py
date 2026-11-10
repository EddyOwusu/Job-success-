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
    "Testing": ["unit testing", "unit tests", "tdd", "test-driven", "pytest", "jest", "automated testing",
                "automated tests", "test automation", "integration tests", "integration testing", "end-to-end tests",
                "e2e tests", "test coverage", "testing frameworks", "well-tested", "writing tests"],
    "Agile": ["agile", "scrum", "kanban"],
    "System Design": ["system design", "distributed systems", "scalable systems"],
    "Security": ["application security", "appsec", "owasp", "secure coding", "security engineering",
                 "security best practices", "cyber security", "cybersecurity", "infosec", "penetration testing",
                 "threat modelling", "threat modeling", "secure software", "security principles"],
    "Payments": ["payments", "payment systems"],
}

# Short names that are also English words; only their explicit patterns are used
# (Security and Testing: the bare word appears in "security-first company", "A/B testing"...)
AMBIGUOUS = {"Go", "R", "C", "Security", "Testing"}

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


@lru_cache(maxsize=1)
def _matcher():
    """One combined pattern for every plain alias (a single pass over the text), plus the few
    special patterns (Go, R, C) that need their own context checks."""
    literal: dict[str, str] = {}
    special: list[tuple[str, re.Pattern]] = []
    for canon, aliases in TAXONOMY.items():
        extra = [] if canon in AMBIGUOUS else [canon.lower()]
        for a in aliases + extra:
            if a.startswith("\\b") or "(?=" in a:
                special.append((canon, re.compile(a, re.I)))
            else:
                literal.setdefault(a, canon)
    alts = sorted(literal, key=len, reverse=True)          # longest first: "react native" before "react"
    big = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(a) for a in alts) + r")(?![a-z0-9+#])")
    return big, literal, special


def find_skills(text: str) -> list[tuple[int, str]]:
    """(position, canonical skill) for every skill mention in the text."""
    text = text or ""
    big, literal, special = _matcher()
    out: list[tuple[int, str]] = []
    for m in big.finditer(text.lower()):
        alias = m.group(1)
        out.append((m.start(), literal[alias]))
        if " " in alias:                                   # "ruby on rails" also means Ruby
            for word in alias.split():
                if word in literal and literal[word] != literal[alias]:
                    out.append((m.start(), literal[word]))
    for canon, pat in special:
        out += [(m.start(), canon) for m in pat.finditer(text)]
    return out


def extract_skills(text: str) -> set[str]:
    return {canon for _, canon in find_skills(text)}


def extract_weighted(text: str) -> dict[str, float]:
    """Skills in the advert with a weight: 1.0 required, 0.4 nice-to-have, 0.7 unknown section,
    0.3 for the intro before the requirements (usually the company describing itself)."""
    text = text or ""
    found = find_skills(text)
    if not found:
        return {}
    from bisect import bisect_right

    lines = text.split("\n")
    has_sections = any(len(l.strip()) < 80 and not l.strip().startswith("-") and REQUIRED_HEADERS.search(l)
                       for l in lines[1:])
    section_weight = 0.3 if has_sections else 0.7
    starts, line_weights, offset = [], [], 0
    for n, line in enumerate(lines):
        starts.append(offset)
        offset += len(line) + 1
        stripped = line.strip()
        if n == 0 and has_sections:      # the job title always counts in full
            line_weights.append(1.0)
            continue
        is_header = len(stripped) < 80 and not stripped.startswith("-")
        if is_header and NICE_TO_HAVE_HEADERS.search(stripped):
            section_weight = 0.4
        elif is_header and REQUIRED_HEADERS.search(stripped):
            section_weight = 1.0
        line_weights.append(0.4 if NICE_TO_HAVE_HEADERS.search(stripped) else section_weight)
    weights: dict[str, float] = {}
    for pos, skill in found:
        w = line_weights[bisect_right(starts, pos) - 1]
        if w > weights.get(skill, 0):
            weights[skill] = w
    return weights
