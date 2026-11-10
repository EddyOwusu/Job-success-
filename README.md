# Job-success: a personal agent for landing a sponsored UK tech job

`jobagent` is a Python agent built to get one person hired in UK tech on a
**Skilled Worker visa**. Every day it:

1. **Searches deep.** It reads the career pages (Greenhouse, Lever, Ashby,
   SmartRecruiters) of 85+ known UK tech employers, plus every sponsor-licensed
   company it has *discovered*, plus Reed and Adzuna if you add free API keys.
2. **Keeps only jobs that can sponsor you.** It checks every employer against the
   Home Office **register of licensed sponsors** (downloaded from gov.uk, about
   123,000 Skilled Worker sponsors), reads the advert for "we can't sponsor" or
   security-clearance wording, and checks the salary against Skilled Worker
   thresholds.
3. **Scores the fit.** Each job gets an explainable 0-100 score (skills, title,
   seniority, location, salary, sponsorship, freshness). Then Claude does a
   recruiter-style deep read of the best ones: fit score, verdict, gaps, red flags
   and talking points.
4. **Tailors your application.** It writes a CV and cover letter for each job,
   using the advert's language **only where it's true**. A fact-checker strips
   any skill, role, certificate or number that isn't in your master CV. Output is
   ATS-friendly DOCX + PDF, with an ATS keyword-coverage report.
5. **Applies.** It opens the application form in a browser, fills it in (name,
   CV upload, cover letter, screening questions answered from your profile),
   then either waits for you to press Submit (`review`, the default) or submits
   itself (`auto`).
6. **Tells you who to talk to.** For each application it writes a networking plan:
   which people to find (hiring manager, recruiter, an engineer on the team, people
   who moved to the UK on a visa), ready-made LinkedIn and Google X-ray search
   links, contacts published in the advert or found with Hunter.io, likely email
   formats, and short outreach and follow-up messages with send dates.
7. **Announces what matters.** A daily digest (Markdown, email, phone push) shows
   the best new matches and suggestions such as: *"Terraform appears in 38% of your
   best matches"*, *"Add 'Platform Engineer' to your targets: 12 jobs fit your
   skills"*, *"Monzo has 5 roles for you: network there first"*, *"3 follow-ups due
   today"*, *"20 applications and no interviews: change approach"*.

## Quick start

```bash
git clone <this repo> && cd Job-success-
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[apply]"            # or: pip install -r requirements.txt
playwright install chromium          # for automatic form filling

jobagent init                        # creates config/profile.yaml, config/cv_master.yaml, config/settings.yaml, .env
# 1. fill in config/profile.yaml   (who you are, what you want, visa situation)
# 2. fill in config/cv_master.yaml (EVERYTHING you've done; the more facts, the better the CVs)
# 3. put your ANTHROPIC_API_KEY (and optional keys) in .env

jobagent doctor                      # checks your setup
jobagent discover                    # finds job boards of licensed sponsors (run weekly)
jobagent run --mode pack             # first run: search, score, assess, build application packs
jobagent list                        # your shortlist
jobagent show <id>                   # why a job scored as it did, plus Claude's assessment
jobagent apply <id>                  # fill the form in a browser; you check it and press Submit
```

Your personal files (`config/profile.yaml`, `config/cv_master.yaml`,
`config/settings.yaml`, `.env`, `data/*.db`, `output/`) are git-ignored and never
leave your machine, apart from the job and CV text sent to the Claude API.

## Daily use

| Command | What it does |
|---|---|
| `jobagent run` | The full daily loop: search, score, assess, prepare the best matches, digest, notify |
| `jobagent run --mode review --max-apply 5` | Also open the 5 best applications in a browser for you to submit |
| `jobagent apply --top 5` | Prepare and apply to the 5 best shortlisted jobs |
| `jobagent apply <id> --mode dry` | Fill the form in a hidden browser and save a screenshot; never submits |
| `jobagent mark-applied <id>` | You applied by hand: track it and schedule follow-ups |
| `jobagent followups` | Messages and nudges due today |
| `jobagent status <id> interview` | Update the pipeline (interview, offer, rejected...) |
| `jobagent network <id>` | Networking plan for any job |
| `jobagent insights` | The agent's suggestions |
| `jobagent sponsors --check "Monzo" "Revolut"` | Is a company a licensed sponsor? |
| `jobagent discover --max 800` | Probe more sponsor companies for job boards |

Each prepared application lands in `output/applications/<date>_<company>_<title>/`:

```
jane-doe-cv.docx / .pdf             tailored, ATS-friendly CV
jane-doe-cover-letter.docx / .pdf   tailored cover letter
job.md          the advert, your score, Claude's assessment, ATS check, anything the fact-checker removed
answers.md      answers to the form's questions (CHECK marks the ones you must verify)
networking.md   who to contact, search links, messages and when to send them
form-filled.png screenshot of the filled form (browser modes)
```

### Run it every morning (cron)

```cron
# 07:10 every day: search, assess, prepare packs, send the digest
10 7 * * * cd /path/to/Job-success- && .venv/bin/jobagent run --mode pack >> output/cron.log 2>&1
# Mondays: refresh the sponsor register and discover more company job boards
40 6 * * 1 cd /path/to/Job-success- && .venv/bin/jobagent sponsors --update && .venv/bin/jobagent discover
```

Then each evening run `jobagent apply --top 5` (review mode), check each form and
press Submit. That takes about 15 minutes a day for 5 strong, tailored applications.

## Apply modes

Set `apply.mode` in `config/settings.yaml`, or pass `--mode`:

- **`pack`**: build the files only. You apply yourself.
- **`review`** (default): the browser opens with everything filled in. You check it,
  press Submit, then type `y` so it's tracked.
- **`auto`**: submits by itself, but only when every required field has a
  confident answer and there is no CAPTCHA. Otherwise it falls back to review.
  It is limited by `max_applications_per_day` (10) and
  `max_per_company_per_30_days` (2), because spraying one company looks bad to
  its recruiters.

Recommendation: stay on `review` for the first 20 or so applications, read what
the agent writes, improve your master CV, then decide about `auto`.

## How it decides what's worth your time

Keyword score (0-100, no AI needed):

| Part | Weight | Notes |
|---|---|---|
| Skills | 35 | Required skills count more than nice-to-haves; your level per skill counts |
| Title | 20 | Against your target roles (first ones count most) |
| Seniority | 10 | Title level and "N+ years" against your experience |
| Location | 10 | Your cities, remote-UK, or relocation |
| Salary | 10 | Meets the Skilled Worker threshold and your minimum |
| Sponsorship | 10 | On the register (A-rated), advert offers sponsorship |
| Freshness | 5 | Applying in the first week matters |

**Blockers** (score capped at 20 and the job is skipped): the advert says it can't
sponsor, the employer isn't on the register (configurable), security clearance is
required, salary below the visa threshold, or an excluded title or company.

Jobs above `scoring.shortlist_threshold` (60) go to Claude for a deep assessment.
Jobs Claude rates at least `scoring.apply_threshold` (70) get application packs.

## Discovery: finding jobs others miss

`jobagent discover` turns sponsor-register names into likely job-board slugs
("Thought Machine Group Limited" becomes `thoughtmachine` / `thought-machine`)
and checks Greenhouse, Lever and Ashby. A hit is a career page at a company
**already licensed to sponsor you**, and many of those jobs never reach LinkedIn or
Indeed. It tries the most promising names first (tech words, tech-hub towns,
A-rated, not recruitment or outsourcing firms) and remembers what it has already
checked, so each weekly run goes deeper. Add your own dream companies in
`data/seed_companies.yaml` or `targets.dream_companies`.

## Visa facts the agent uses (check them yourself)

- Only employers on the [register of licensed sponsors](https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers)
  can sponsor a Skilled Worker visa. The agent refreshes it every 3 days.
- Salary rules: `sponsorship.general_threshold_gbp` (default £41,700) and
  `new_entrant_threshold_gbp` (£33,400) in settings. Each occupation also has a
  "going rate" that can be higher. **Rules change often: check
  [gov.uk/skilled-worker-visa](https://www.gov.uk/skilled-worker-visa/your-job)
  and update the settings.** You can enter going rates for your occupation code
  under `sponsorship.going_rates_gbp`.
- You may qualify for the lower **new entrant** rate if you're under 26, recently
  graduated, or switching from a Student or Graduate visa. Set `visa.new_entrant: true` if so.
- If you studied in the UK, the **Graduate visa** gives you two years of right to
  work without sponsorship, which makes you a much easier hire. Set
  `visa.current_uk_right_to_work: true` while you hold it.

## Honesty rules (built in)

- No invented experience. The fact-checker removes skills, employers, titles,
  dates, certificates and numbers that aren't in your master CV, and lists what
  it removed in `job.md`.
- No ATS tricks such as white-text keyword stuffing. Recruiters spot them and
  reject the CV. The CVs beat ATS filters by being relevant: standard headings,
  the advert's exact skill names where they're true, one column, real text.
- Visa and right-to-work answers always state your real situation. A wrong
  answer can lose you the offer at the right-to-work check.
- No LinkedIn scraping (it breaks LinkedIn's terms and gets accounts banned).
  The agent gives you precise search links instead. No CAPTCHA solving.

## Optional API keys (`.env`)

| Key | Free? | Adds |
|---|---|---|
| `ANTHROPIC_API_KEY` | paid | Claude: deep assessment, tailored CVs and letters, form answers, outreach messages. Without it you get keyword scoring and templates |
| `REED_API_KEY` | yes | Reed.co.uk search ([get a key](https://www.reed.co.uk/developers/jobseeker)) |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | yes | Adzuna search across UK boards ([get keys](https://developer.adzuna.com/)) |
| `HUNTER_API_KEY` | free tier | Recruiter and manager emails by company domain |
| `NTFY_TOPIC` | yes | Push notifications to your phone via the ntfy app |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | yes | Telegram notifications |
| `SMTP_*`, `NOTIFY_EMAIL_TO` | yes | Email digest (Gmail: use an App Password) |

Claude cost: the model is `claude-opus-5-5` (change `llm.model` in settings). A
deep assessment is roughly 6-10k input tokens and 1k output; a full application
(CV, letter, answers, outreach) is about 4 calls. Your profile and CV are prompt-cached
across calls. `llm.max_assessments_per_run` (25) caps daily spend. Requests use
server-side fallbacks, so a request a safety classifier declines is retried on a
recommended fallback model instead of failing.

## Project layout

```
jobagent/
  cli.py            commands
  pipeline.py       the daily loop
  sources/          greenhouse, lever, ashby, smartrecruiters, reed, adzuna
  sponsors.py       Home Office sponsor register: download + fuzzy name matching
  discovery.py      finds job boards of licensed sponsors
  visa.py           sponsorship wording, clearance, salary thresholds
  skills.py         skill taxonomy + extraction (required vs nice-to-have)
  matching.py       explainable scoring
  llm.py prompts.py Claude structured outputs
  assess.py         deep fit assessment
  tailor.py         CV / cover letter / form answers + fact-checker
  ats.py            ATS keyword coverage
  render.py         DOCX / PDF / Markdown
  apply/            application packs, browser form filling, rule-based answers
  networking.py     contacts, search links, email patterns, outreach messages
  insights.py       suggestions; digest.py; notify.py
config/             example profile and master CV (copy them with `jobagent init`)
data/seed_companies.yaml   starting list of employers' job boards
tests/              pytest suite (run: python -m pytest)
```
