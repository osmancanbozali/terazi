# Agentic Trading Hackathon — Official Rules & Evaluation Criteria

## 1. Event Overview

- **Event:** Agentic Trading Hackathon
- **Organizer:** Komünite
- **Official page:** https://komunite.com.tr/etkinlikler/agentic-trading-hackathon
- **Format:** In-person, individual hackathon
- **Location:** Komünite Space, Vadistanbul
- **Date:** September 12, 2026
- **Participant limit:** 35 participants
- **Participation fee:** Free
- **Prize pool:** $5,000

## 2. Main Objective

The goal is to build an autonomous AI trading agent that can operate in real market conditions using the infrastructure provided by OKX TR.

The agent is expected to:

1. Observe market data.
2. Generate trading decisions based on a strategy.
3. Apply risk management.
4. Execute trades through the provided exchange infrastructure.
5. Operate autonomously.
6. Produce measurable trading performance.

This is not merely a backtesting or presentation competition. The agent is expected to trade in the competition account under real market conditions.

---

## 3. Trading Environment

### Exchange

- **Exchange / infrastructure:** OKX TR
- **Market:** Spot market
- **Account:** Competition-specific sub-account
- **Capital:** Trading credit provided by OKX TR
- **API access:** Participant-specific API access
- **Personal capital:** Participants are not expected to deposit their own funds for the competition.

### Account Requirements

- Participants must have an OKX TR account.
- OKX TR membership and KYC must be completed.
- A dedicated competition sub-account must be created.
- The API key used for the competition must belong to the relevant sub-account.

### Important Trading Restriction

Only trades executed autonomously by the agent are considered for evaluation.

Manual trades are not included in performance evaluation and may result in disqualification if they violate the competition rules.

---

# 4. Evaluation Criteria

The total evaluation consists of five criteria.

| Criterion | Weight |
|---|---:|
| Competition Account Performance | 35% |
| Agent Architecture & Autonomy | 25% |
| Risk Management | 20% |
| Strategy Originality | 10% |
| Presentation & Demo | 10% |
| **Total** | **100%** |

---

## 4.1. Competition Account Performance — 35%

### Official focus

The agent's performance in the competition account, including:

- Return
- Risk-adjusted return
- Maximum drawdown

### Metrics

#### A. Return

Measures how much profit or loss the agent generates during the competition.

The exact official return calculation formula is not specified on the event page.

#### B. Risk-Adjusted Return

Measures performance relative to the risk taken.

The event explicitly mentions risk-adjusted return, but does not specify the exact metric or formula.

The following are NOT confirmed as official formulas:

- Sharpe Ratio
- Sortino Ratio
- Calmar Ratio
- Any other specific risk-adjusted metric

Do not assume one of these is the official scoring formula without confirmation from the organizers.

#### C. Maximum Drawdown (MDD)

Measures the largest decline from a portfolio peak to a subsequent trough during the evaluation period.

The event explicitly lists maximum drawdown as a performance consideration.

### Important Notes

- Performance is measured using the competition account.
- Manual trades are not included in the evaluation.
- The exact formula used to combine return, risk-adjusted return, and maximum drawdown is not specified on the event page.
- The exact starting balance / trading credit amount is not specified on the event page.

---

## 4.2. Agent Architecture & Autonomy — 25%

### Official focus

The evaluation considers:

- Decision-loop design
- Tool usage
- Fault tolerance
- Reliable operation without human intervention

### A. Decision-Loop Design

The architecture and logic through which the agent:

1. Observes market conditions.
2. Processes relevant information.
3. Generates a decision.
4. Executes or rejects an action.
5. Monitors the result.
6. Continues the next decision cycle.

### B. Tool Usage

The agent's ability to interact with external tools and infrastructure.

Potential examples include:

- Market data APIs
- Order book / ticker data
- Order placement APIs
- Open orders
- Positions
- Account balance
- Trade history

The event evaluates tool usage as part of agent architecture, but does not prescribe a specific framework or tool-calling implementation.

### C. Fault Tolerance

The agent should be able to handle operational failures and unexpected conditions.

Potential examples:

- API timeouts
- Connection failures
- Invalid or incomplete data
- Failed orders
- Unexpected API responses
- Temporary service failures

The event explicitly lists fault tolerance as an evaluation consideration, but does not publish a detailed fault-tolerance checklist.

### D. Reliable Autonomous Operation

The agent should be capable of operating without continuous human intervention.

The agent should not depend on a human manually deciding when to buy or sell.

### Important Notes

- The event does not mandate a specific LLM provider.
- The event does not mandate a specific AI model.
- The event does not mandate a specific agent framework.
- The event does not explicitly require every trading decision to be generated by an LLM.
- The exact scoring rubric for this 25% category is not published on the event page.

---

## 4.3. Risk Management — 20%

### Official focus

The evaluation considers:

- Position sizing
- Stop-loss discipline
- Resilience to extreme scenarios

### A. Position Sizing

How the agent determines the size of each position or order.

Relevant considerations may include:

- Account balance
- Risk per trade
- Current exposure
- Position limits
- Market conditions
- Available liquidity

The event does not prescribe a specific position-sizing formula.

### B. Stop-Loss Discipline

How the agent manages losses and exits positions when a predefined risk threshold is reached.

Relevant considerations may include:

- Whether stop-loss logic exists
- Whether it is consistently applied
- Whether the mechanism works reliably
- How the system behaves after a stop-loss is triggered

The event explicitly mentions stop-loss discipline but does not prescribe a specific stop-loss methodology.

### C. Extreme Scenario Resilience

How the agent behaves under abnormal or adverse market and system conditions.

Potential examples:

- Sudden price movements
- High volatility
- Low liquidity
- API failures
- Partial order execution
- Delayed market data
- Unexpected system errors

The event explicitly evaluates resilience to extreme scenarios, but does not publish a detailed list of mandatory scenarios.

### Important Notes

- Risk management has a separate 20% weighting.
- Risk management should be part of the agent's actual behavior, not merely a presentation claim.
- The event does not prescribe specific risk limits, stop percentages, or position-size formulas.

---

## 4.4. Strategy Originality — 10%

### Official focus

The evaluation considers:

- Originality of signal generation
- Ability to interpret market microstructure

### A. Original Signal Generation

The strategy should demonstrate an original or differentiated approach to generating trading signals.

The event does not prescribe a specific strategy.

### B. Market Microstructure Understanding

The strategy may be evaluated on how well it interprets market microstructure.

Relevant concepts may include:

- Order-book imbalance
- Bid-ask spread
- Trade flow
- Market depth
- Liquidity
- Slippage
- Short-term market behavior

These are examples of market microstructure concepts. The event does not state that any particular one is mandatory.

### Important Notes

- Strategy originality accounts for 10% of the total score.
- The event does not require a specific trading strategy.
- The event does not require the use of a specific indicator, model, or market-microstructure signal.
- The exact scoring rubric for originality is not published.

---

## 4.5. Presentation & Demo — 10%

### Official focus

The evaluation considers:

- Clarity of the story
- Smoothness of the live demo
- Ability to prove the strategy in 3 minutes

### Expected Presentation Content

The presentation should clearly communicate:

1. What the strategy does.
2. How the agent works.
3. How the agent makes decisions.
4. How risk is managed.
5. What happened in the competition account.
6. Why the strategy is meaningful or differentiated.

### 3-Minute Strategy Proof

The event explicitly emphasizes the ability to prove the strategy within 3 minutes.

The presentation should prioritize:

- Clear strategy hypothesis
- Concise architecture explanation
- Risk-management explanation
- Actual performance evidence
- Working demo

### Important Notes

- Presentation and demo account for 10% of the total score.
- The exact presentation format and detailed scoring rubric are not specified on the event page.
- The 3-minute presentation structure should not be confused with a detailed official slide template unless provided by the organizers.

---

# 5. Competition Schedule

The official event schedule is:

| Time | Activity |
|---|---|
| 07:30 | Doors open / Registration |
| 08:00–08:20 | Opening and briefing |
| 08:20 | Elevator pitch |
| 09:00 | Official start |
| 10:00–16:00 | Mentors and development |
| 17:30 | Final check-in |
| 19:00–19:30 | Submission and file lock |
| 20:00 | Presentations |
| 21:30 | Jury evaluation |
| 22:15 | Award ceremony |

### Important Deadlines

- **19:00–19:30:** Submission preparation and file lock
- **19:30:** Submission folder closes and competition-account performance is recorded
- **20:00:** Presentations begin

---

# 6. Submission Requirements

The event page lists the following submission materials:

- README
- Short video / GIF
- Competition account performance report
- Working agent link
- Presentation files

### Suggested README Structure

The following is a planning recommendation, not an official README template:

1. Project overview
2. Strategy hypothesis
3. System architecture
4. Agent decision loop
5. Tool usage
6. Risk management
7. Trading results
8. Setup and run instructions
9. Limitations

---

# 7. General Rules

## 7.1. Individual Participation

- Participation is individual.
- Team participation is not permitted according to the event rules.

## 7.2. Autonomous Trading

- Evaluation-relevant trades must be executed autonomously by the agent.
- Manual trades are not included in performance evaluation.
- Manual trading may lead to disqualification if it violates the rules.

## 7.3. Competition Account

- Trading must be performed through the designated competition sub-account.
- The API key must belong to the relevant competition account.
- Personal accounts or personal balances are not used for competition evaluation.

## 7.4. Pre-Built Systems

Presenting a previously completed system as if it had been built from scratch during the hackathon may result in disqualification.

Open-source libraries may be used in accordance with their licenses.

Participants may use their own tools, provided that doing so does not violate the competition rules.

## 7.5. Intellectual Property

The event states that intellectual property remains with the participants.

## 7.6. Technical Infrastructure

Participants are expected to bring:

- Their own laptop
- Their own power adapter / charger

The event provides infrastructure such as internet access, cables, and power outlets.

---

# 8. Officially Unspecified Details

The following details are not explicitly specified on the event page and should not be assumed during planning:

- Exact risk-adjusted return formula
- Exact performance scoring formula
- Exact starting trading credit amount
- Allowed trading pairs
- Maximum position size
- Minimum order size
- Maximum number of orders
- API rate limits
- Allowed order types
- Exact stop-loss requirements
- Exact risk limits
- Exact LLM or model requirement
- Required agent framework
- Required programming language
- Exact fault-tolerance test cases
- Exact jury scoring rubric for each subcriterion
- Whether a specific framework such as LangGraph, CrewAI, or another agent framework is required

These details should be confirmed with the organizers or in the official technical documentation before implementation.

---

# 9. Key Planning Constraints

When planning the project, optimize for the following weighted priorities:

1. **Competition performance — 35%**
   - Return
   - Risk-adjusted return
   - Maximum drawdown

2. **Agent architecture and autonomy — 25%**
   - Decision loop
   - Tool usage
   - Fault tolerance
   - Reliable autonomous operation

3. **Risk management — 20%**
   - Position sizing
   - Stop-loss discipline
   - Extreme-scenario resilience

4. **Strategy originality — 10%**
   - Original signal generation
   - Market microstructure understanding

5. **Presentation and demo — 10%**
   - Clear story
   - Smooth demo
   - Strategy proof in 3 minutes

## Core Principle

The project should not be planned as merely an LLM chatbot that produces BUY/SELL suggestions.

The target is an autonomous trading system that can:

- Observe market data
- Make strategy-driven decisions
- Use tools
- Apply risk controls
- Execute trades
- Monitor outcomes
- Operate reliably without continuous human intervention
- Produce measurable performance evidence
