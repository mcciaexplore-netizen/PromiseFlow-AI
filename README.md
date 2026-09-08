# PromiseFlow AI

Run locally without Supabase using SQLite: [local operation guide](docs/LOCAL.md). PostgreSQL is optional: [Supabase connection guide](docs/SUPABASE.md).

**Know whether a commitment is achievable before you make it.**

## V3 decision-intelligence update

Promise Checker now opens first. Planning readiness, freshness warnings and explicit assumptions accompany decisions. Background requests persist status; identical inputs reuse versioned cached solves. Resource-by-day load and material-to-customer dependency views expose planning context. Proposal review supports saved notes, terminal rejection and complete decision JSON export.

Correctness fixes include indefinite quality holds, visible blocked orders, preserved shift breaks during overtime, conservative time rounding, hard deadlines, duplicate-input rejection, complete worsening-commitment comparisons and stronger independent publication validation. Demo/production database separation is enforced in both directions. Imports add key masters, column mapping and revision-safe rollback. Overtime cost measures only added-calendar work.

Read the [V3 audit](docs/V3_AUDIT.md), [implementation report](docs/V3_IMPLEMENTATION_REPORT.md), [known limitations](docs/KNOWN_LIMITATIONS.md), [performance](docs/PERFORMANCE.md), and [pilot guide](docs/PILOT_GUIDE.md). This is a phased pilot release; execution reconciliation, shared SaaS tenancy, advanced manufacturing constraints and large-factory optimization remain release gates.

A working manufacturing planning MVP for MCCIA AI Applied Studio. It checks delivery promises against a finite-capacity production model, explores recovery scenarios, and requires explicit approval to activate a new schedule.

The schedule comes from **Google OR-Tools CP-SAT**, never a language model. The application includes a React/TypeScript interface, a FastAPI service, SQLite or private PostgreSQL persistence, realistic synthetic factory data, downloadable Excel templates, and automated constraint/API tests.

## Run locally on Windows

Requirements: Python 3.12 and Node.js 24. Run from this repository:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd --prefix frontend ci
npm.cmd run build
.\start.ps1
```

Open **http://127.0.0.1:8017**. The single server serves both the compiled interface and API. Initial demo creation runs one optimization and can take several seconds.

Local demo sign-in: select **Production manager**, password **promise-demo**. Demo roles are `manager`, `planner`, `sales`, `supervisor`, `purchase`, `maintenance`, `management`, and `admin`. Each role has the same password only in the synthetic demo environment. Manager/admin can activate proposals; planner can edit and propose; sales can check promises; maintenance/purchase can simulate; other roles read the plan.

The development preview is http://127.0.0.1:5173. Run the API on 8017 and `npm.cmd run dev` in a second terminal. Vite proxies `/api` to the Python service.

On macOS/Linux, use `.venv/bin/python` instead of `.venv\Scripts\python.exe`, and run `python -m uvicorn backend.app:app --host 127.0.0.1 --port 8017` after building.

## Try the product

1. Open **Promise Checker** to inspect readiness, or Dashboard for computed delivery risk and resource utilization.
2. Open **Promise Checker**, enter a new order, and check the requested date. Approved operations are fixed during this first solve; no master data or active plan changes.
3. Inspect material/resource/vendor evidence. A solver-limited late incumbent is **At risk**, not a false proof of infeasibility. “Earliest feasible” appears only when candidate completion is proven optimal with the current plan fixed.
4. Compare recovery options: reoptimization across eligible machines, longer resource shifts, or earlier incoming material. Review every existing order’s dispatch-date change and newly at-risk count.
5. In **What-If Simulator**, evaluate breakdowns, operator absence, material/supplier delays, maintenance, indefinite quality holds, extra shifts, quantity/date changes, qualified alternatives/outsourcing, and smaller transfer batches. A quality hold never expires based on elapsed duration.
6. In **Rescheduling**, inspect proposed delivery outcomes and operation moves. **Approve & activate** opens a confirmation with the customer impact; only manager/admin can complete it. Stale proposals are rejected.
7. In **Imports**, download a template, upload XLSX/CSV, fix row/column validation errors, preview, then apply. Build a new plan to use changed master data.

## Implemented modules

Dashboard; Orders; Products; Routings; Resources; Materials; Production Plan; Promise Checker; Bottlenecks; What-If Simulator; Disruptions; Rescheduling; Reports; Imports; Settings.

Settings includes calendars, tools, operator crews, customers, suppliers, weighted planning objectives and an audit trail. Advanced master records use a validated JSON editor; orders and main decisions have dedicated forms. The Gantt supports date ranges, zoom, resource/search filters, late/at-risk highlighting, downtime overlays and operation inspection. It intentionally has no drag-and-drop mutation.

## Planning contract

- Universal resource model: machines, lines, inspection stations, tools, operators and external vendors are configuration, not CNC-specific engine code.
- Order → transfer-batch job → routing operations. All batches must complete before dispatch; per-operation transfer and queue minutes are included.
- Optional intervals choose one eligible resource/operator assignment per operation. Cumulative constraints enforce resource, tool and operator capacity.
- Each batch operation fits a contiguous working window, including setup; there is no hidden overnight production. Continuous external calendars can span midnight. Large operations need a smaller transfer batch or a larger working window.
- Materials are allocated deterministically by order/customer priority and due date. Reservations and safety stock reduce availability. All material for an order is reserved at its earliest batch release. One incoming replenishment per material is supported. This conservative allocation is **not** jointly optimized with resource sequencing.
- A deterministic greedy feasible assignment provides hints. CP-SAT solves the actual constrained model with one worker, fixed seed and a deterministic search budget. Results report `OPTIMAL`, `FEASIBLE`, `INFEASIBLE`, `UNKNOWN` or `MODEL_INVALID`; only feasible, complete schedules can activate.
- Default weighted objective penalizes priority-weighted late orders and tardiness, then includes makespan and configured production cost. It is a weighted sum, not a strict lexicographic guarantee. Revenue does not determine priority.
- Promise mode minimizes the candidate completion while fixing approved work. Recovery mode can move unreleased work and shows the impact. Work marked RELEASED or IN PRODUCTION keeps approved assignments.
- A separate validator rechecks quantities, coverage, durations, eligible resources, calendars, materials, capacities, operators, tooling, precedence and delivery completion before activation.

## Persistence and approvals

SQLite uses WAL, transactional writes and optimistic revisions. Master entities have unique `(kind,id)` keys and typed cross-reference validation. Schedule versions store immutable factory inputs, solver settings, complete results, parent version, author and reason. Approval metadata is added once; older versions remain available. A proposal can activate only when its source data revision and active parent still match.

Master edits and imports do **not** overwrite the active schedule. The approved result always retains its original inputs. This is a single-plant, single-tenant application; SQLite or private PostgreSQL plus one API worker is the deployment scope of this MVP.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd run build
npm.cmd run lint
```

Tests exercise independent schedule validity, repeatability, exclusive/shared capacities, material arrivals/shortages, reservations, tools, skills, holidays, maintenance, external lead time, batch splitting, frozen promises, locked operations, role enforcement, approvals, stale writes, import preview/apply and formula rejection.

## Deployment and scope

See [architecture](docs/ARCHITECTURE.md), [deployment](docs/DEPLOYMENT.md), [MVP scope and limits](docs/SCOPE.md), and the live API schema at `/docs`.

This is an implemented and tested MVP, **not a claim of plant-validated production readiness**. Before real commitments, calibrate the factory data, verify scheduling assumptions with PPC, and complete the deployment acceptance checks. V3.1 adds a [Shop Floor log and whole-order reconciliation](docs/EXECUTION.md). Partial-work rescheduling, sequence-dependent cleaning/changeovers, preemptive operations, multi-site tenancy, and enterprise SSO remain unimplemented. The optional LLM copilot is intentionally absent; explanations are deterministic.
