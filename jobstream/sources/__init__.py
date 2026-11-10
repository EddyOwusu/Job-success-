"""Job sources. ATS boards (company career pages) plus UK job-board APIs."""
from . import adzuna, ashby, greenhouse, jobsacuk, lever, nhs, reed, smartrecruiters, workday

ATS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "smartrecruiters": smartrecruiters,
    "workday": workday,          # banks, insurers, pharma, media, retail...
}
AGGREGATORS = {
    "reed": reed,
    "adzuna": adzuna,
    "nhs": nhs,                  # NHS Jobs: every NHS trust in England and Wales
    "jobsacuk": jobsacuk,        # universities and research institutes
}
