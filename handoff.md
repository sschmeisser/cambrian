# Project Handoff: GitHub Sync & Branham High Schedule / Standings Audit

**Timestamp:** 2026-09-26 14:02 PDT  
**Target Repository:** `sschmeisser/cambrian`  
**Current Branch / Commit:** `main` @ `c7bf6e0` (Up to date with `origin/main`)

---

## 1. Quick Answers & Critical Instructions

### Q1: How to change to "Auto-Allow" in Antigravity
If Antigravity is prompting you for confirmation on terminal commands or file changes:
1. **Via UI Settings:**
   - Click the **Gear icon (Settings)** in the bottom left or left navigation sidebar.
   - Navigate to **Agent Settings** (or **Permissions / Tool Execution**).
   - Under **Tool Execution Policy** (or **Auto-Execution Policy**), select **`always-proceed`** (or toggle "Always Allow Execution").
   - Under **Terminal Sandbox**, you can also set permissions to allow execution without sandbox review prompts.
2. **Via Individual Confirmation Prompts:**
   - When a confirmation modal pops up in chat for a command, click the dropdown or checkbox for **"Always allow for this command prefix"** or **"Always allow in this workspace"**.

---

## 2. GitHub Status Check
- Checked `origin/main` and executed `git pull origin main`.
- The local repository was fast-forwarded to `c7bf6e0` (`chore(auto): refresh scores, standings & calendar [2026-09-26 16:59]`).
- Recent upstream commits included schedule repopulations from ESPN APIs (`63461a3`) and automated cron refresh cycles.

---

## 3. Root Cause Analysis: Branham High & BVAL Discrepancies

### A. Why the Schedule Was Incorrect
- **ESPN API Limitation:** While NFL, NHL, NBA, MLS, and NCAA schedules were pulled from ESPN APIs, high school schedules cannot be sourced from ESPN.
- **Hallucinated Fixtures in `scripts/repopulate_schedules.py`:** The high school schedule block (`hs_schedule`) was populated with placeholder fixtures and fake results:
  - **Week 0 (Sep 18):** Populated as Willow Glen @ Branham (Fake final: Branham 28-14).
  - **Week 1 (Sep 25 - Yesterday):** Populated as **`Leigh High Longhorns @ Branham High Bruins`** (upcoming).
  - **Weeks 2–6:** Had Branham playing every single game at home (`Branham Stadium`).

### B. What Actually Happened Yesterday (Friday, September 25, 2026)
Ground truth verified via MaxPreps and CIF Central Coast Section records:
1. **Branham High Bruins:**
   - Was **AWAY at Live Oak** in Morgan Hill.
   - **Result:** **Live Oak 54, Branham 15** (Final).
2. **Leigh High Longhorns:**
   - Was **AWAY at Willow Glen** in San Jose.
   - **Result:** **Willow Glen 28, Leigh 13** (Final).
3. **The Branham vs. Leigh Rivalry Game:**
   - **Does NOT take place in September.**
   - It is scheduled for **Friday, October 16, 2026 at 7:15 PM** at **Branham Stadium** (Week 4).

### C. Why the Standings Were Incorrect
- In `data/standings.json` and `league_standings.py`, the `hs_bval` table had fabricated end-of-season numbers from a past year or simulation:
  - Listed Branham as **9–1** (Division Leader) and Leigh as **8–2**.
- **Ground Truth 2026 Season:**
  - Blossom Valley Athletic League (BVAL) Mount Hamilton Division is split into North and South. Branham and Leigh are in **Mount Hamilton - North**.
  - **League games have NOT started yet** (all teams are 0–0 in conference play).
  - **Real Standings as of September 26, 2026:**
    1. **Santa Teresa Saints:** 4–1 (0–0 Conf)
    2. **Leland Chargers:** 3–1 (0–0 Conf)
    3. **Pioneer Mustangs:** 1–2 (0–0 Conf)
    4. **Leigh Longhorns:** 1–4 (0–0 Conf)
    5. **Piedmont Hills Pirates:** 0–4 (0–0 Conf)
    6. **Branham High Bruins:** 0–5 (0–0 Conf) [Points For: 89, Points Against: 205]

---

## 4. Ground-Truth Data Reference (2026 Season)

### Branham Bruins Full 2026 Schedule & Results
| Date | Day & Time | Opponent | Location / Venue | Status & Score |
| :--- | :--- | :--- | :--- | :--- |
| **2026-08-28** | Fri 7:00 PM | vs. San Mateo Bearcats | Home (Branham Stadium) | **L 20–42** (Final) |
| **2026-09-05** | Sat 1:30 PM | @ Ann Sobrato Bulldogs | Away (Sobrato Stadium, Morgan Hill) | **L 13–50** (Final) |
| **2026-09-10** | Thu 7:00 PM | vs. Willow Glen Rams | Home (Branham Stadium) | **L 20–28** (Final) |
| **2026-09-18** | Fri 7:00 PM | vs. Lincoln Lions | Home (Branham Stadium) | **L 21–31** (Final) |
| **2026-09-25** | Fri 7:15 PM | @ Live Oak Acorns | Away (Live Oak Stadium, Morgan Hill) | **L 15–54** (Final - Yesterday) |
| **2026-10-02** | Fri | *BYE WEEK* | — | — |
| **2026-10-09** | Fri 7:15 PM | @ Piedmont Hills Pirates | Away (Pirate Stadium, San Jose) | Upcoming (BVAL Opener) |
| **2026-10-16** | Fri 7:15 PM | vs. Leigh Longhorns | Home (Branham Stadium) | Upcoming (**Cambrian Derby**) |
| **2026-10-23** | Fri 7:15 PM | vs. Santa Teresa Saints | Home (Branham Stadium) | Upcoming (Homecoming) |
| **2026-10-30** | Fri 7:15 PM | @ Leland Chargers | Away (Pat Tillman Stadium, Leland) | Upcoming |
| **2026-11-06** | Fri 7:15 PM | @ Pioneer Mustangs | Away (Mustang Stadium, Pioneer) | Upcoming (Regular Season Finale) |

### Leigh Longhorns 2026 Key Games
- **2026-09-25:** @ Willow Glen (L 13–28) [Yesterday]
- **2026-10-02:** *BYE WEEK*
- **2026-10-09:** @ Pioneer (7:15 PM)
- **2026-10-16:** @ Branham (7:15 PM - Cambrian District Derby)
- **2026-10-23:** vs. Leland (7:15 PM)
- **2026-10-30:** vs. Piedmont Hills (7:15 PM)
- **2026-11-05:** vs. Santa Teresa (7:15 PM)

---

## 5. Next Steps / Implementation Plan (When Resuming)

When you return and start up again, here are the exact steps to apply the clean fixes:

1. **Update `league_standings.py` & `data/standings.json`:**
   - Update `hs_bval` subtitle to `"2026 Blossom Valley Athletic League (Mount Hamilton - North)"`.
   - Update rows with real records:
     - Santa Teresa (4-1, Conf 0-0)
     - Leland (3-1, Conf 0-0)
     - Pioneer (1-2, Conf 0-0)
     - Leigh (1-4, Conf 0-0)
     - Piedmont Hills (0-4, Conf 0-0)
     - Branham (0-5, Conf 0-0, PF 89, PA 205)

2. **Update `data/games.json` and `scripts/repopulate_schedules.py`:**
   - **Week 0 (`w0-07`):** Replace fake Willow Glen 28-14 game with `Lincoln Lions (31) @ Branham High Bruins (21)` (Final).
   - **Week 1 (`w1-07`):** Replace fake `Leigh @ Branham` game with:
     - Game 1: `Branham High Bruins (15) @ Live Oak Acorns (54)` (Final, Played Friday Sep 25).
     - Game 2: `Leigh High Longhorns (13) @ Willow Glen Rams (28)` (Final, Played Friday Sep 25).
     - Update Week 1 title (remove "The Campbell District Derby" since it's on Oct 16).
   - **Week 2:** Mark Branham as BYE (or remove fake Live Oak @ Branham).
   - **Week 3:** Set `Branham High Bruins @ Piedmont Hills Pirates` (Away at Pirate Stadium).
   - **Week 4:** Set `Leigh High Longhorns @ Branham High Bruins` (Home at Branham Stadium, "The Campbell Union District Derby / Cambrian Derby").
   - **Week 5:** Set `Santa Teresa Saints @ Branham High Bruins` (Home at Branham Stadium).
   - **Week 6:** Set `Branham High Bruins @ Leland Chargers` (Away at Pat Tillman Stadium).

3. **Rebuild Static HTML:**
   - Run `python3 build_calendar.py` to regenerate `sports_calendar.html` and `index.html`.

4. **Verify & Push:**
   - Inspect output in browser.
   - Commit changes: `git commit -am "fix: correct Branham & Leigh 2026 schedules and BVAL standings"` and `git push origin main`.
