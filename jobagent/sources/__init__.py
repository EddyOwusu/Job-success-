"""Job sources. ATS boards (company career pages) plus UK job-board APIs."""
from . import adzuna, ashby, greenhouse, lever, reed, smartrecruiters

ATS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "smartrecruiters": smartrecruiters,
}
AGGREGATORS = {
    "reed": reed,
    "adzuna": adzuna,
}
