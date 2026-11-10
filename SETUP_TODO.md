# Your setup checklist

Everything you need to do on your PC, in order. Tick items off by changing `[ ]` to `[x]`.
Nothing here contains personal data, so it is safe in the repository.

## 1. Install (about 10 minutes)

- [ ] Install Python 3.10 or newer (python.org) and Git, if you don't have them
- [ ] Get the code:
  ```bash
  git clone https://github.com/EddyOwusu/Job-success-.git
  cd Job-success-
  git checkout claude/dreamy-clarke-xemmiq
  ```
- [ ] Create the environment and install:
  ```bash
  python -m venv .venv
  # Windows:    .venv\Scripts\activate
  # Mac/Linux:  source .venv/bin/activate
  pip install -e ".[apply]"
  playwright install chromium
  ```
- [ ] Create your private files: `jobagent init`

## 2. Keys (in the `.env` file; never paste keys into a chat)

- [ ] `ANTHROPIC_API_KEY`: your Claude API key (needed for assessments, tailored CVs, statements, interview prep)
- [ ] In the Claude Console, check that **web search** is allowed for your organisation
      (used for interview and company research; everything else works without it)
- [ ] Optional, free: `REED_API_KEY` (reed.co.uk/developers/jobseeker)
- [ ] Optional, free: `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` (developer.adzuna.com)
- [ ] Optional: `HUNTER_API_KEY` (recruiter emails by company)

## 3. Your profile (`config/profile.yaml`)

- [ ] Name, email, phone, location, LinkedIn, GitHub
- [ ] `targets.roles`: include titles used outside tech, e.g. "Software Developer", "Systems Developer",
      "Integration Developer", "Research Software Engineer"
- [ ] `targets.locations`, `min_salary_gbp`, `seniority`, `years_experience`
- [ ] `skills`: every skill, with honest years and level
- [ ] `education`: institution, `graduation_year`, `graduation_month`, `country`, `uk_degree`
- [ ] `visa`: `needs_sponsorship`, `current_status`, `current_uk_right_to_work`, `nationality`,
      `date_of_birth` (optional, checks the under-26 salary rule), `had_graduate_visa`
- [ ] `visa.new_entrant: true` if you're under 26, a recent graduate, or on a Student/Graduate visa
      (lowers the salary bar from £41,700 to £33,400 and reopens many NHS and university jobs)
- [ ] `standard_answers`: notice period, salary expectation, and the diversity answers you prefer

## 4. Your master CV (`config/cv_master.yaml`)

- [ ] Every role, with dates, and every achievement as a bullet (numbers and tech named)
- [ ] Projects, education, certifications
- [ ] `stories`: 4-6 short stories (a hard bug, a conflict, a deadline, why the UK...). The agent uses
      these for form answers, statements and interview prep. It never invents facts beyond this file.

## 5. First run

- [ ] `jobagent doctor`: checks the setup
- [ ] `jobagent visa`: which visa routes are open to you (HPI, Scale-up, new-entrant rate), checked on gov.uk
- [ ] `jobagent discover`: finds more sponsor job boards (takes a few minutes)
- [ ] `jobagent run --mode pack`: first full run (about 10 minutes the first time, 1-2 minutes after)
- [ ] `jobagent dashboard --open`: everything on one page
- [ ] `jobagent list`, then `jobagent show <id>` on the top few
- [ ] `jobagent apply <id> --mode dry` once, to see a filled form without submitting
- [ ] `jobagent apply --top 3`: check each form, press Submit yourself

## 6. Phone alerts and email

- [ ] Phone push: install the **ntfy** app, subscribe to a hard-to-guess topic name, and put that name
      in `.env` as `NTFY_TOPIC`. This is what delivers "Apply today" alerts.
- [ ] Email digest: Gmail App Password in `.env` (`SMTP_USER`, `SMTP_PASSWORD`, `NOTIFY_EMAIL_TO`)
- [ ] Inbox reading: turn on IMAP in Gmail settings; `IMAP_USER` / `IMAP_PASSWORD` in `.env`
      (or leave blank to reuse the SMTP login). Test with `jobagent inbox`.

## 7. Put it on a timetable

- [ ] `jobagent schedule`: shows the timetable (07:10 full run, three quick checks a day, Monday discovery)
- [ ] `jobagent schedule --install`: sets it up in Windows Task Scheduler (or cron on Mac/Linux).
      Your PC must be on and awake at those times.

## 8. Weekly habits

- [ ] Daily, 2 min: read the push and digest, or open the dashboard
      (`jobagent dashboard --lan` shows it on your phone over home Wi-Fi)
- [ ] Daily, 15 min: `jobagent apply --top 5`, check and submit
- [ ] Daily, 10 min: send the networking messages; `jobagent followups`
- [ ] Weekly: `jobagent speculative`, then `--build 3`, send them, `--sent "<company>"`
- [ ] Weekly: `jobagent learn` (what's working) and `jobagent radar` (newly licensed sponsors)
- [ ] Weekly: `jobagent grow`. If a skill keeps costing you jobs, `--plan` a two-week project for it,
      build it, then `--done "<skill>"` and paste the snippet into your profile and master CV
- [ ] If the digest says a source "looks broken": run `jobagent health` and pull the latest code
- [ ] When you get an interview: `jobagent status <id> interview` (builds your prep pack)

## 9. Check these facts yourself

- [ ] Salary thresholds on gov.uk/skilled-worker-visa/your-job (`jobagent visa` warns you if they change)
- [ ] The going rate for your occupation code (e.g. 2134 programmers); add it under
      `sponsorship.going_rates_gbp` in `config/settings.yaml`
- [ ] Stay on `review` mode for your first 20 applications before considering `auto`
